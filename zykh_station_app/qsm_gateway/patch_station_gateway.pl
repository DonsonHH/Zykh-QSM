#!/usr/bin/env perl

use strict;
use warnings;
use File::Copy qw(copy);

my $target = $ARGV[0] || '/userdata/zykh_app/server.pl';
my $backup = "$target.before-empty-request-exit";

open my $input, '<:raw', $target or die "Cannot read $target: $!\n";
local $/;
my $source = <$input>;
close $input;

my $changed = 0;

if ($source !~ /ZYKH_STATION_CHILD_EMPTY_REQUEST_EXIT/) {
    my $pattern = qr{
        if\s*\(\s*!\$req\s*\)\s*\{\s*
        close\s+\$client\s*;\s*
        next\s*;\s*
        \}
    }x;
    my $replacement = <<'PERL';
if (!$req) {
            close $client;
            # ZYKH_STATION_CHILD_EMPTY_REQUEST_EXIT
            exit 0;
        }
PERL
    my $matches = () = $source =~ /$pattern/g;
    die "Expected exactly one empty-request child block, found $matches\n" unless $matches == 1;
    $source =~ s/$pattern/$replacement/;
    $changed = 1;
}

if ($source !~ /ZYKH_STATION_CAMERA_STREAM_IDLE_EXIT/) {
    my $before = <<'PERL';
    my $last_path = '';
    my $last_mtime = 0;
    my $delay = 1 / $fps;
    while (1) {
        my $path = latest_stream_frame();
        if ($path && -s $path) {
            my $mtime = (stat($path))[9] || 0;
            if ($path ne $last_path || $mtime != $last_mtime) {
                open my $fh, '<:raw', $path or last;
                local $/;
                my $jpg = <$fh>;
                close $fh;
                if ($jpg && length($jpg) > 1000) {
                    my $head = "--$boundary\r\nContent-Type: image/jpeg\r\nContent-Length: " . length($jpg) . "\r\n\r\n";
                    last unless print {$client} $head;
                    last unless print {$client} $jpg;
                    last unless print {$client} "\r\n";
                    $last_path = $path;
                    $last_mtime = $mtime;
                }
            }
        }
        select(undef, undef, undef, $delay);
    }
PERL
    my $after = <<'PERL';
    my $last_path = '';
    my $last_mtime = 0;
    my $idle_ticks = 0;
    my $delay = 1 / $fps;
    while (1) {
        my $sent_frame = 0;
        my $path = latest_stream_frame();
        if ($path && -s $path) {
            my $mtime = (stat($path))[9] || 0;
            if ($path ne $last_path || $mtime != $last_mtime) {
                open my $fh, '<:raw', $path or last;
                local $/;
                my $jpg = <$fh>;
                close $fh;
                if ($jpg && length($jpg) > 1000) {
                    my $head = "--$boundary\r\nContent-Type: image/jpeg\r\nContent-Length: " . length($jpg) . "\r\n\r\n";
                    last unless print {$client} $head;
                    last unless print {$client} $jpg;
                    last unless print {$client} "\r\n";
                    $last_path = $path;
                    $last_mtime = $mtime;
                    $sent_frame = 1;
                }
            }
        }
        # ZYKH_STATION_CAMERA_STREAM_IDLE_EXIT
        $idle_ticks = $sent_frame ? 0 : $idle_ticks + 1;
        last if $idle_ticks >= $fps * 3;
        select(undef, undef, undef, $delay);
    }
PERL
    my $matches = () = $source =~ /\Q$before\E/g;
    die "Expected exactly one MJPEG stream loop, found $matches\n" unless $matches == 1;
    $source =~ s/\Q$before\E/$after/;
    $changed = 1;
}

if ($source !~ /ZYKH_STATION_AUDIO_STOP_ALL_V2/) {
    my $pattern = qr{
        if\s*\(\s*\$method\s+eq\s+'POST'\s*&&\s*\$path\s+eq\s+'/api/audio/stream/stop'\s*\)\s*\{\s*
        (?:\#\s*ZYKH_STATION_AUDIO_STOP_ALL\s*)?
        return\s+send_json\(\$client,\s*200,\s*(?:stop_audio_pcm_stream|release_audio_playback_device)\(\)\);\s*
        \}
    }x;
    my $replacement = <<'PERL';
if ($method eq 'POST' && $path eq '/api/audio/stream/stop') {
        # ZYKH_STATION_AUDIO_STOP_ALL
        # ZYKH_STATION_AUDIO_STOP_ALL_V2
        return send_json($client, 200, release_audio_playback_device());
    }
PERL
    my $matches = () = $source =~ /$pattern/g;
    die "Expected exactly one audio stream stop route, found $matches\n" unless $matches == 1;
    $source =~ s/$pattern/$replacement/;
    $changed = 1;
}

# The presentation mode now chooses between cloud TTS and the board's offline
# Sherpa-ONNX voice. Restore the route on devices that previously received the
# host-only guard, and mark an untouched route idempotently.
if ($source !~ /ZYKH_STATION_QSM_TTS/) {
    my $disabled_pattern = qr{
        if\s*\(\s*\$method\s+eq\s+'POST'\s*&&\s*\$path\s+eq\s+'/api/audio/speak'\s*\)\s*\{\s*
        \#\s*ZYKH_STATION_[A-Z_]+\s*
        return\s+send_json\(\$client,\s*200,\s*\{.*?
        mode\s*=>\s*'host-offline-tts-required'.*?
        \}\);\s*
        \}
    }xs;
    my $pattern = qr{
        if\s*\(\s*\$method\s+eq\s+'POST'\s*&&\s*\$path\s+eq\s+'/api/audio/speak'\s*\)\s*\{\s*
        return\s+send_json\(\$client,\s*200,\s*speak_text\(\$req-\>\{params\}\)\);\s*
        \}
    }x;
    my $replacement = <<'PERL';
if ($method eq 'POST' && $path eq '/api/audio/speak') {
        # ZYKH_STATION_QSM_TTS
        return send_json($client, 200, speak_text($req->{params}));
    }
PERL
    my $disabled_matches = () = $source =~ /$disabled_pattern/g;
    die "Expected at most one disabled TTS route, found $disabled_matches\n"
        if $disabled_matches > 1;
    if ($disabled_matches == 1) {
        $source =~ s/$disabled_pattern/$replacement/;
        $changed = 1;
    } else {
        my $matches = () = $source =~ /$pattern/g;
        die "Expected exactly one board TTS route, found $matches\n" unless $matches == 1;
        $source =~ s/$pattern/$replacement/;
        $changed = 1;
    }
}

if ($source !~ /ZYKH_STATION_TTS_PROCESS_GROUP/) {
    my $before = <<'PERL';
sub run_tts_command {
    my ($cmd, $log, $timeout) = @_;
    my $rc;
    {
        local $SIG{CHLD} = 'DEFAULT';
        $rc = system('timeout', int($timeout || 90), 'sh', '-c', $cmd . ' >' . shell_quote($log) . ' 2>&1');
    }
    my $exit = $rc == -1 ? -1 : ($rc >> 8);
    return {
        ok => $exit == 0 ? JSON::PP::true : JSON::PP::false,
        exit_code => $exit,
        detail => substr(read_text_file($log) || '', 0, 500),
    };
}
PERL
    my $after = <<'PERL';
sub run_tts_command {
    my ($cmd, $log, $timeout) = @_;
    my $pidfile = "$DATA_DIR/audio-tts.pid";
    my $pid;
    my $rc = -1;
    {
        local $SIG{CHLD} = 'DEFAULT';
        $pid = fork();
        if (defined($pid) && $pid == 0) {
            # ZYKH_STATION_TTS_PROCESS_GROUP
            eval { POSIX::setpgid(0, 0); };
            exec('timeout', int($timeout || 90), 'sh', '-c', $cmd . ' >' . shell_quote($log) . ' 2>&1');
            exit 127;
        }
        if (defined $pid) {
            eval { POSIX::setpgid($pid, $pid); };
            my $cancel_file = "$DATA_DIR/audio-tts-cancel-$pid";
            unlink $cancel_file if -f $cancel_file;
            write_text_file($pidfile, "$pid\n");
            waitpid($pid, 0);
            $rc = $?;
        }
    }
    return {
        ok => JSON::PP::false,
        exit_code => -1,
        detail => "Cannot fork managed TTS command: $!",
    } unless defined $pid;

    my $cancel_file = "$DATA_DIR/audio-tts-cancel-$pid";
    my $cancelled = -f $cancel_file;
    unlink $cancel_file if $cancelled;
    if (-f $pidfile && read_file_trim($pidfile) eq "$pid") {
        unlink $pidfile;
    }
    my $exit = $rc == -1 ? -1 : ($rc >> 8);
    return {
        ok => !$cancelled && $exit == 0 ? JSON::PP::true : JSON::PP::false,
        cancelled => $cancelled ? JSON::PP::true : JSON::PP::false,
        exit_code => $exit,
        detail => substr(read_text_file($log) || '', 0, 500),
    };
}
PERL
    my $matches = () = $source =~ /\Q$before\E/g;
    die "Expected exactly one legacy run_tts_command implementation, found $matches\n"
        unless $matches == 1;
    $source =~ s/\Q$before\E/$after/;
    $changed = 1;
}

if ($source !~ /ZYKH_STATION_TTS_CANCEL_HELPER/) {
    my $anchor = "sub release_audio_playback_device {\n";
    my $helper = <<'PERL';
sub cancel_tts_command_process_group {
    # ZYKH_STATION_TTS_CANCEL_HELPER
    my $pidfile = "$DATA_DIR/audio-tts.pid";
    my $pid = -f $pidfile ? read_file_trim($pidfile) : '';
    if ($pid =~ /^\d+$/) {
        my $cancel_file = "$DATA_DIR/audio-tts-cancel-$pid";
        write_text_file($cancel_file, "cancelled\n");
        kill 'TERM', -int($pid);
        for (1..20) {
            last unless kill(0, -int($pid));
            select(undef, undef, undef, 0.05);
        }
        kill 'KILL', -int($pid) if kill(0, -int($pid));
        if (-f $pidfile && read_file_trim($pidfile) eq "$pid") {
            unlink $pidfile;
        }
        return {
            ok => JSON::PP::true,
            cancelled => JSON::PP::true,
            pid => int($pid),
        };
    }
    unlink $pidfile if -f $pidfile;
    return {
        ok => JSON::PP::true,
        cancelled => JSON::PP::false,
    };
}

PERL
    my $matches = () = $source =~ /\Q$anchor\E/g;
    die "Expected exactly one release_audio_playback_device anchor, found $matches\n"
        unless $matches == 1;
    $source =~ s/\Q$anchor\E/$helper$anchor/;
    $changed = 1;
}

if ($source !~ /ZYKH_STATION_RELEASE_CANCELS_TTS/) {
    my $before = <<'PERL';
sub release_audio_playback_device {
    stop_audio_pcm_stream();
    system('sh', '-c', 'killall aplay 2>/dev/null');
    select(undef, undef, undef, 0.18);
    return { ok => JSON::PP::true };
}
PERL
    my $after = <<'PERL';
sub release_audio_playback_device {
    # ZYKH_STATION_RELEASE_CANCELS_TTS
    my $tts = cancel_tts_command_process_group();
    stop_audio_pcm_stream();
    system('sh', '-c', 'killall aplay 2>/dev/null');
    select(undef, undef, undef, 0.18);
    return {
        ok => JSON::PP::true,
        tts_cancelled => $tts->{cancelled},
    };
}
PERL
    my $matches = () = $source =~ /\Q$before\E/g;
    die "Expected exactly one legacy release_audio_playback_device implementation, found $matches\n"
        unless $matches == 1;
    $source =~ s/\Q$before\E/$after/;
    $changed = 1;
}

if ($source !~ /ZYKH_STATION_TTS_CANCEL_RESULT/) {
    my $before = <<'PERL';
        my $run = run_tts_command($attempt->{command}, $log, $attempt->{timeout});
        if ($run->{ok}) {
PERL
    my $after = <<'PERL';
        my $run = run_tts_command($attempt->{command}, $log, $attempt->{timeout});
        # ZYKH_STATION_TTS_CANCEL_RESULT
        if ($run->{cancelled}) {
            return {
                ok => JSON::PP::false,
                cancelled => JSON::PP::true,
                mode => 'cancelled',
                requested_mode => $requested_mode,
                error => '语音播报已取消',
            };
        }
        if ($run->{ok}) {
PERL
    my $matches = () = $source =~ /\Q$before\E/g;
    die "Expected exactly one speak_text command result block, found $matches\n"
        unless $matches == 1;
    $source =~ s/\Q$before\E/$after/;
    $changed = 1;
}

if ($source !~ /ZYKH_STATION_DISPENSE_OPERATION_IDEMPOTENCY_V1/) {
    my $anchor = "sub dispense {\n";
    my $replacement = <<'PERL';
# ZYKH_STATION_DISPENSE_OPERATION_IDEMPOTENCY_V1
sub dispense_operation_file_key {
    my ($operation_id) = @_;
    my $key = "$operation_id";
    $key =~ s/([^A-Za-z0-9_.-])/sprintf('%%%02X', ord($1))/ge;
    return $key;
}

sub read_dispense_operation_state {
    my ($path) = @_;
    return (undef, '') unless -f $path;
    open my $fh, '<:raw', $path
        or return (undef, "无法读取既有出药预留：$!");
    local $/;
    my $raw = <$fh>;
    close $fh;
    my $state = eval { JSON::PP::decode_json($raw || '') };
    return (undef, '既有出药预留已损坏') unless ref($state) eq 'HASH';
    return ($state, '');
}

sub write_dispense_operation_state {
    my ($path, $state) = @_;
    my $encoded = eval { JSON::PP::encode_json($state) };
    return (0, "无法编码出药预留：$@") unless defined $encoded;
    my $temporary = "$path.tmp.$$";
    open my $fh, '>:raw', $temporary
        or return (0, "无法创建出药预留：$!");
    if (!print {$fh} $encoded) {
        my $error = $!;
        close $fh;
        unlink $temporary;
        return (0, "无法写入出药预留：$error");
    }
    if (!close $fh) {
        my $error = $!;
        unlink $temporary;
        return (0, "无法落盘出药预留：$error");
    }
    if (!rename $temporary, $path) {
        my $error = $!;
        unlink $temporary;
        return (0, "无法提交出药预留：$error");
    }
    return (1, '');
}

sub dispense_operation_unknown_result {
    my ($operation_id, $detail) = @_;
    return {
        ok => JSON::PP::false,
        result => 'result_unknown',
        result_unknown => JSON::PP::true,
        retry_safe => JSON::PP::false,
        operation_id => $operation_id,
        detail => $detail || '上次出药可能已经发送，结果待现场确认；禁止自动重试。',
    };
}

sub dispense {
    my ($p) = @_;
    $p = {} unless ref($p) eq 'HASH';
    my $operation_id = exists $p->{operation_id} ? "$p->{operation_id}" : '';
    return dispense_once($p) if $operation_id eq '';
    return {
        ok => JSON::PP::false,
        result => 'invalid_operation_id',
        operation_id => $operation_id,
        error => 'operation_id 格式不合法',
    } unless $operation_id =~ /\A[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\z/;

    my $slot = int($p->{slot} || 0);
    return { ok => JSON::PP::false, error => '仓位必填', operation_id => $operation_id }
        if $slot <= 0;
    return { ok => JSON::PP::false, error => '仓位超出范围：1-23', operation_id => $operation_id }
        if $slot > 23;
    my $quantity_text = exists $p->{quantity} ? "$p->{quantity}" : '1';
    return {
        ok => JSON::PP::false,
        result => 'invalid_quantity',
        operation_id => $operation_id,
        error => '取药数量必须为正整数',
    } unless $quantity_text =~ /\A\d+\z/ && int($quantity_text) > 0;
    my $quantity = int($quantity_text);
    my $control_code = exists $p->{control_code} && "$p->{control_code}" =~ /^\d+$/
        ? int($p->{control_code})
        : cabinet_control_code($slot);
    return { ok => JSON::PP::false, error => '控制码超出范围：0-22', operation_id => $operation_id }
        if $control_code < 0 || $control_code > 22;

    my $key = dispense_operation_file_key($operation_id);
    my $state_path = "$DATA_DIR/dispense-operation-$key.json";
    my $lock_path = "$DATA_DIR/dispense-operation-$key.lock";
    open my $lock, '>>:raw', $lock_path
        or return dispense_operation_unknown_result($operation_id, "无法锁定出药预留：$!");
    if (!flock($lock, 2)) {
        my $error = $!;
        close $lock;
        return dispense_operation_unknown_result($operation_id, "无法锁定出药预留：$error");
    }

    my ($existing, $read_error) = read_dispense_operation_state($state_path);
    if ($read_error) {
        close $lock;
        return dispense_operation_unknown_result($operation_id, $read_error);
    }
    if ($existing) {
        my $same_payload =
            ($existing->{operation_id} || '') eq $operation_id
            && int($existing->{slot} || 0) == $slot
            && int($existing->{quantity} || 0) == $quantity
            && defined($existing->{control_code})
            && int($existing->{control_code}) == $control_code;
        if (!$same_payload) {
            close $lock;
            return {
                ok => JSON::PP::false,
                result => 'idempotency_conflict',
                idempotency_conflict => JSON::PP::true,
                operation_id => $operation_id,
                error => '同一 operation_id 的仓位、数量或控制码不一致',
            };
        }
        if (($existing->{state} || '') eq 'final' && ref($existing->{final_result}) eq 'HASH') {
            my %replayed = %{$existing->{final_result}};
            $replayed{operation_id} = $operation_id;
            $replayed{replay} = JSON::PP::true;
            close $lock;
            return \%replayed;
        }
        close $lock;
        return dispense_operation_unknown_result(
            $operation_id,
            '上次出药已预留或已发送，但没有最终结果；请现场确认，禁止自动重试。',
        );
    }

    my $timestamp = now_text();
    my $state = {
        schema_version => 1,
        operation_id => $operation_id,
        slot => $slot,
        quantity => $quantity,
        control_code => $control_code,
        state => 'reserved',
        created_at => $timestamp,
        updated_at => $timestamp,
    };
    my ($reserved, $reserve_error) = write_dispense_operation_state($state_path, $state);
    if (!$reserved) {
        close $lock;
        return {
            ok => JSON::PP::false,
            result => 'reservation_failed',
            operation_id => $operation_id,
            error => $reserve_error,
        };
    }

    $state->{state} = 'sent';
    $state->{updated_at} = now_text();
    my ($sent, $sent_error) = write_dispense_operation_state($state_path, $state);
    if (!$sent) {
        close $lock;
        return dispense_operation_unknown_result($operation_id, $sent_error);
    }

    my $result;
    my $completed = eval {
        $result = dispense_once($p);
        1;
    };
    if (!$completed || ref($result) ne 'HASH') {
        my $detail = $@ || '出药执行没有返回有效结果';
        close $lock;
        return dispense_operation_unknown_result($operation_id, $detail);
    }
    my %final_result = %$result;
    $final_result{operation_id} = $operation_id;
    $final_result{replay} = JSON::PP::false;
    $state->{state} = 'final';
    $state->{final_result} = \%final_result;
    $state->{updated_at} = now_text();
    my ($finalized, $finalize_error) = write_dispense_operation_state($state_path, $state);
    if (!$finalized) {
        close $lock;
        return dispense_operation_unknown_result($operation_id, $finalize_error);
    }
    close $lock;
    return \%final_result;
}

sub dispense_once {
PERL
    my $matches = () = $source =~ /\Q$anchor\E/g;
    die "Expected exactly one dispense implementation, found $matches\n" unless $matches == 1;
    $source =~ s/\Q$anchor\E/$replacement/;
    $changed = 1;
}

if ($source =~ /ZYKH_STATION_DISPENSE_OPERATION_IDEMPOTENCY_V1/
        && $source =~ /sub\s+write_dispense_operation_state\s*\{/
        && $source !~ /ZYKH_STATION_DISPENSE_OPERATION_DURABLE_V2/) {
    my $before = <<'PERL';
sub write_dispense_operation_state {
    my ($path, $state) = @_;
    my $encoded = eval { JSON::PP::encode_json($state) };
    return (0, "无法编码出药预留：$@") unless defined $encoded;
    my $temporary = "$path.tmp.$$";
    open my $fh, '>:raw', $temporary
        or return (0, "无法创建出药预留：$!");
    if (!print {$fh} $encoded) {
        my $error = $!;
        close $fh;
        unlink $temporary;
        return (0, "无法写入出药预留：$error");
    }
    if (!close $fh) {
        my $error = $!;
        unlink $temporary;
        return (0, "无法落盘出药预留：$error");
    }
    if (!rename $temporary, $path) {
        my $error = $!;
        unlink $temporary;
        return (0, "无法提交出药预留：$error");
    }
    return (1, '');
}
PERL
    my $after = <<'PERL';
# ZYKH_STATION_DISPENSE_OPERATION_DURABLE_V2
sub write_dispense_operation_state {
    my ($path, $state) = @_;
    my $io_handle_loaded = eval { require IO::Handle; 1 };
    return (0, "系统不支持可靠出药预留落盘：$@") unless $io_handle_loaded;
    my $encoded = eval { JSON::PP::encode_json($state) };
    return (0, "无法编码出药预留：$@") unless defined $encoded;
    my $temporary = "$path.tmp.$$";
    open my $fh, '>:raw', $temporary
        or return (0, "无法创建出药预留：$!");
    if (!print {$fh} $encoded) {
        my $error = $!;
        close $fh;
        unlink $temporary;
        return (0, "无法写入出药预留：$error");
    }
    if (!$fh->flush()) {
        my $error = $!;
        close $fh;
        unlink $temporary;
        return (0, "无法刷新出药预留：$error");
    }
    if (!$fh->sync()) {
        my $error = $!;
        close $fh;
        unlink $temporary;
        return (0, "无法同步出药预留：$error");
    }
    if (!close $fh) {
        my $error = $!;
        unlink $temporary;
        return (0, "无法关闭出药预留：$error");
    }
    if (!rename $temporary, $path) {
        my $error = $!;
        unlink $temporary;
        return (0, "无法提交出药预留：$error");
    }
    open my $directory, '<', $DATA_DIR
        or return (0, "无法打开出药预留目录：$!");
    if (!$directory->sync()) {
        my $error = $!;
        close $directory;
        return (0, "无法同步出药预留目录：$error");
    }
    if (!close $directory) {
        return (0, "无法关闭出药预留目录：$!");
    }
    return (1, '');
}
PERL
    my $matches = () = $source =~ /\Q$before\E/g;
    die "Expected exactly one legacy dispense operation writer, found $matches\n"
        unless $matches == 1;
    $source =~ s/\Q$before\E/$after/;
    $changed = 1;
}

if ($source !~ /ZYKH_STATION_DISPENSE_HARDWARE_SEAM_V2/) {
    my $pattern = qr{
        sub\s+dispense_once\s*\{\s*
        my\s*\(\$p\)\s*=\s*\@_;\s*
    }x;
    my $replacement = <<'PERL';
sub station_dispense_executor_available {
    my ($p) = @_;
    my $slot = int($p->{slot} || 0);
    my $uart_dev = $ENV{DISPENSE_UART} || '/dev/ttyS5';
    my $mode = $ENV{DISPENSE_MODE} || 'uart';
    my $gpio = $ENV{"SLOT${slot}_GPIO"};
    return 1 if $mode eq 'uart' && $uart_dev && -e $uart_dev;
    return 1 if defined($gpio) && "$gpio" =~ /^\d+$/;
    return 0;
}

sub dispense_once {
    my ($p) = @_;
    $p = {} unless ref($p) eq 'HASH';
    # ZYKH_STATION_DISPENSE_HARDWARE_SEAM_V2
    if (!station_dispense_executor_available($p)) {
        return {
            ok => JSON::PP::false,
            result => 'hardware_unavailable',
            result_unknown => JSON::PP::false,
            retry_safe => JSON::PP::true,
            error => '未检测到可用 UART5 或仓位 GPIO，本次未执行开柜。',
            detail => '未检测到可用 UART5 或仓位 GPIO，本次未执行开柜。',
        };
    }
    my $hardware_lock_path = "$DATA_DIR/dispense-hardware.lock";
    open my $hardware_lock, '>>:raw', $hardware_lock_path
        or return {
            ok => JSON::PP::false,
            result => 'hardware_lock_unavailable',
            result_unknown => JSON::PP::false,
            retry_safe => JSON::PP::true,
            error => "无法锁定药柜执行器：$!",
        };
    if (!flock($hardware_lock, 2)) {
        my $error = $!;
        close $hardware_lock;
        return {
            ok => JSON::PP::false,
            result => 'hardware_lock_unavailable',
            result_unknown => JSON::PP::false,
            retry_safe => JSON::PP::true,
            error => "无法锁定药柜执行器：$error",
        };
    }
PERL
    my $matches = () = $source =~ /$pattern/g;
    die "Expected exactly one dispense_once implementation, found $matches\n"
        unless $matches == 1;
    $source =~ s/$pattern/$replacement/;
    $changed = 1;
}

if (!$changed) {
    print "Station gateway reliability fixes already installed.\n";
    exit 0;
}

my $temporary = "$target.station-patch.$$";
open my $output, '>:raw', $temporary or die "Cannot write $temporary: $!\n";
print {$output} $source;
close $output;

system('perl', '-c', $temporary) == 0 or do {
    unlink $temporary;
    die "Patched station gateway did not compile\n";
};

copy($target, $backup) or die "Cannot create $backup: $!\n" unless -f $backup;
rename $temporary, $target or die "Cannot replace $target: $!\n";
chmod 0755, $target;
print "Installed station gateway reliability fixes.\n";
