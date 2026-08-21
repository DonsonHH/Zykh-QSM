package Zykh::CabinetLightProtocol;

use strict;
use warnings;
use utf8;

use Fcntl qw(O_NOCTTY O_RDWR);
use IO::Select ();
use JSON::PP ();
use Time::HiRes qw(time);

sub new {
    my ($class, %args) = @_;
    my $timeout = 0 + ($args{timeout_seconds} || 2);
    $timeout = 2 if $timeout <= 0;
    return bless {
        device => $args{device} || '/dev/ttyACM0',
        baud => int($args{baud} || 115200),
        timeout_seconds => $timeout,
    }, $class;
}

sub illuminate {
    my ($self, $cabinet_id) = @_;
    my $cabinet_text = defined($cabinet_id) ? "$cabinet_id" : '';
    return _failure(
        result => 'invalid_cabinet',
        error => '分类柜编号必须是 1、2 或 3',
        retry_safe => 1,
    ) unless $cabinet_text =~ /\A[123]\z/;
    $cabinet_id = int($cabinet_text);

    my ($handle, $open_error) = $self->_open_uart();
    return _failure(
        result => 'hardware_unavailable',
        error => $open_error,
        retry_safe => 1,
    ) unless $handle;

    my $command = "CABINET $cabinet_id";
    my $ack = $self->_exchange($handle, $command);
    if (!$ack->{ok}) {
        close $handle;
        return _after_command_failure($ack, "${cabinet_id}号柜亮灯指令");
    }
    if ($ack->{line} ne "OK CABINET $cabinet_id") {
        close $handle;
        return _unknown("分类柜控制器响应不匹配：$ack->{line}");
    }

    my $status = $self->_exchange($handle, 'STATUS');
    close $handle;
    return _after_command_failure($status, '分类柜状态复核') unless $status->{ok};
    return _unknown("分类柜状态复核不匹配：$status->{line}")
        unless $status->{line} eq "STATUS CABINET $cabinet_id";

    return {
        ok => JSON::PP::true,
        result => 'success',
        result_unknown => JSON::PP::false,
        retry_safe => JSON::PP::false,
        cabinet_id => $cabinet_id,
        status => "cabinet_$cabinet_id",
        detail => "${cabinet_id}号柜指示灯已亮起，请用户自行打开亮灯的柜门取药。",
    };
}

sub off {
    my ($self) = @_;
    my ($handle, $open_error) = $self->_open_uart();
    return _failure(
        result => 'hardware_unavailable',
        error => $open_error,
        retry_safe => 1,
    ) unless $handle;

    my $ack = $self->_exchange($handle, 'OFF');
    if (!$ack->{ok}) {
        close $handle;
        return _after_off_failure($ack, '分类柜灭灯指令');
    }
    if ($ack->{line} ne 'OK OFF') {
        close $handle;
        return _off_unknown("分类柜灭灯响应不匹配：$ack->{line}");
    }

    my $status = $self->_exchange($handle, 'STATUS');
    close $handle;
    return _after_off_failure($status, '分类柜灭灯状态复核') unless $status->{ok};
    return _off_unknown("分类柜灭灯状态复核不匹配：$status->{line}")
        unless $status->{line} eq 'STATUS OFF';

    return {
        ok => JSON::PP::true,
        result => 'success',
        result_unknown => JSON::PP::false,
        retry_safe => JSON::PP::false,
        status => 'off',
        detail => '三个分类柜的指示灯均已关闭。',
    };
}

sub status {
    my ($self) = @_;
    my ($handle, $open_error) = $self->_open_uart();
    return _failure(
        result => 'hardware_unavailable',
        error => $open_error,
        retry_safe => 1,
    ) unless $handle;

    my $response = $self->_exchange($handle, 'STATUS');
    close $handle;
    return _failure(
        result => 'status_unavailable',
        error => $response->{error},
        retry_safe => 1,
    ) unless $response->{ok};
    if ($response->{line} eq 'STATUS OFF') {
        return {
            ok => JSON::PP::true,
            result => 'success',
            status => 'off',
            detail => '三个分类柜的指示灯均已关闭。',
        };
    }
    if ($response->{line} =~ /\ASTATUS CABINET ([123])\z/) {
        my $cabinet_id = int($1);
        return {
            ok => JSON::PP::true,
            result => 'success',
            cabinet_id => $cabinet_id,
            status => "cabinet_$cabinet_id",
            detail => "${cabinet_id}号柜指示灯当前亮起。",
        };
    }
    return _failure(
        result => 'protocol_error',
        error => "无法识别分类柜状态响应：$response->{line}",
        retry_safe => 1,
    );
}

sub _open_uart {
    my ($self) = @_;
    my $device = $self->{device};
    return (undef, "分类柜串口不存在：$device") unless $device && -e $device;
    my $baud = $self->{baud};
    $baud = 115200 if $baud <= 0;
    my $configured;
    {
        # server.pl ignores SIGCHLD globally. Restore the default while waiting
        # for stty so a successful child is not misreported as ECHILD.
        local $SIG{CHLD} = 'DEFAULT';
        $configured = system(
            'stty', '-F', $device, "$baud", 'cs8', '-cstopb', '-parenb',
            '-ixon', '-ixoff', '-crtscts', 'clocal', 'raw', '-echo',
            'min', '0', 'time', '0',
        );
    }
    return (undef, "无法配置分类柜串口：$device ${baud}bps") if $configured != 0;

    my $handle;
    return (undef, "无法打开分类柜串口：$device $!")
        unless sysopen($handle, $device, O_RDWR | O_NOCTTY);
    binmode($handle);
    return ($handle, '');
}

sub _exchange {
    my ($self, $handle, $command) = @_;
    my $payload = "$command\r\n";
    my $offset = 0;
    while ($offset < length($payload)) {
        my $written = syswrite($handle, $payload, length($payload) - $offset, $offset);
        if (!defined($written) || $written <= 0) {
            return {
                ok => 0,
                sent => $offset > 0 ? 1 : 0,
                error => "分类柜串口写入失败：$!",
            };
        }
        $offset += $written;
    }

    my $selector = IO::Select->new($handle);
    my $deadline = time() + $self->{timeout_seconds};
    my $buffer = '';
    while (time() < $deadline) {
        my $remaining = $deadline - time();
        my @ready = $selector->can_read($remaining);
        last unless @ready;
        my $chunk = '';
        my $count = sysread($handle, $chunk, 512);
        return {
            ok => 0,
            sent => 1,
            error => "分类柜串口读取失败：$!",
        } unless defined $count;
        last if $count == 0;
        $buffer .= $chunk;
        while ($buffer =~ s/\A([^\r\n]*)(?:\r\n|\n|\r)//) {
            my $line = $1;
            next if $line eq '' || $line eq $command;
            return { ok => 1, sent => 1, line => $line };
        }
        return {
            ok => 0,
            sent => 1,
            error => '分类柜控制器响应过长',
        } if length($buffer) > 1024;
    }
    return {
        ok => 0,
        sent => 1,
        error => "等待分类柜控制器响应超时（命令：$command）",
    };
}

sub _after_command_failure {
    my ($response, $action) = @_;
    return _unknown("$action 结果无法确认：$response->{error}") if $response->{sent};
    return _failure(
        result => 'hardware_unavailable',
        error => "$action 未发送：$response->{error}",
        retry_safe => 1,
    );
}

sub _after_off_failure {
    my ($response, $action) = @_;
    return _off_unknown("$action 结果无法确认：$response->{error}") if $response->{sent};
    return _failure(
        result => 'hardware_unavailable',
        error => "$action 未发送：$response->{error}",
        retry_safe => 1,
    );
}

sub _unknown {
    my ($detail) = @_;
    return _failure(
        result => 'result_unknown',
        error => $detail,
        detail => "$detail；请现场确认指示灯状态，禁止自动重试。",
        result_unknown => 1,
        retry_safe => 0,
    );
}

sub _off_unknown {
    my ($detail) = @_;
    return _failure(
        result => 'result_unknown',
        error => $detail,
        detail => "$detail；请现场确认指示灯状态，灭灯指令可安全重试。",
        result_unknown => 1,
        retry_safe => 1,
    );
}

sub _failure {
    my (%args) = @_;
    return {
        ok => JSON::PP::false,
        result => $args{result} || 'failed',
        result_unknown => $args{result_unknown} ? JSON::PP::true : JSON::PP::false,
        retry_safe => $args{retry_safe} ? JSON::PP::true : JSON::PP::false,
        error => $args{error} || '分类柜控制失败',
        detail => $args{detail} || $args{error} || '分类柜控制失败',
    };
}

1;
