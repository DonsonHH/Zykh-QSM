#!/usr/bin/env perl
use strict;
use warnings;
use utf8;
use IO::Socket::INET;
use JSON::PP qw(encode_json decode_json);
use POSIX qw(strftime);
use Encode qw(decode);

$| = 1;

my $PORT = int($ENV{QSM_FACE_GATEWAY_PORT} || 8081);
my $FACE_HOME = $ENV{QSM_FACE_HOME} || '/userdata/qsm-face';
my $MAIN_GATEWAY = $ENV{QSM_MAIN_GATEWAY_URL} || 'http://127.0.0.1:8080';
my $LOCK_DIR = '/tmp/zykh-face-camera.lock';
my $LOG_DIR = "$FACE_HOME/logs";
my $SEARCH_THRESHOLD = number_env('QSM_FACE_SEARCH_THRESHOLD', 0.38);
my $ACCEPT_THRESHOLD = number_env('QSM_FACE_ACCEPT_THRESHOLD', 0.41);
my $MIN_MATCH_VOTES = int($ENV{QSM_FACE_MIN_MATCH_VOTES} || 3);
my $VOTE_MARGIN = number_env('QSM_FACE_VOTE_MARGIN', 0.035);

mkdir $LOG_DIR unless -d $LOG_DIR;

my $server = IO::Socket::INET->new(
    LocalHost => '0.0.0.0',
    LocalPort => $PORT,
    Proto => 'tcp',
    Listen => 10,
    Reuse => 1,
) or die "Cannot start face gateway on port $PORT: $!\n";

print "QSM face gateway listening on 0.0.0.0:$PORT\n";
$SIG{CHLD} = 'IGNORE';

while (my $client = $server->accept()) {
    my $pid = fork();
    if (!defined $pid) {
        close $client;
        next;
    }
    if ($pid) {
        close $client;
        next;
    }
    eval {
        $client->autoflush(1);
        my $request = read_request($client);
        route_request($client, $request) if $request;
    };
    send_json($client, 500, { ok => JSON::PP::false, status => 'error', error_message => "$@" }) if $@;
    close $client;
    exit 0;
}

sub route_request {
    my ($client, $request) = @_;
    my $path = $request->{path};
    my $method = $request->{method};

    if ($method eq 'GET' && $path eq '/api/face/status') {
        return send_json($client, 200, face_status());
    }
    if ($method eq 'GET' && $path eq '/api/face/list') {
        return send_json($client, 200, list_faces());
    }
    if ($method eq 'POST' && $path eq '/api/face/identify') {
        return send_json($client, 200, identify_face($request->{params}));
    }
    if ($method eq 'POST' && $path eq '/api/face/enroll') {
        return send_json($client, 200, enroll_face($request->{params}));
    }
    return send_json($client, 404, { ok => JSON::PP::false, status => 'not_found', error_message => 'Face API not found' });
}

sub face_status {
    my $camera = $ENV{QSM_FACE_CAMERA} || '/dev/video23';
    my $binary = "$FACE_HOME/qsm_face";
    my $model = "$FACE_HOME/Gundam_RK356X";
    my $list = list_faces();
    my $available = -x $binary && -s $model && -e $camera;
    return {
        ok => $available ? JSON::PP::true : JSON::PP::false,
        status => $available ? 'available' : 'unavailable',
        camera_available => -e $camera ? JSON::PP::true : JSON::PP::false,
        runtime_available => (-x $binary && -s $model) ? JSON::PP::true : JSON::PP::false,
        enrolled_samples => int($list->{sample_count} || 0),
        enrolled_subjects => $list->{subjects} || [],
        search_threshold => $SEARCH_THRESHOLD + 0,
        accept_threshold => $ACCEPT_THRESHOLD + 0,
        min_match_votes => $MIN_MATCH_VOTES,
        error_message => $available ? undef : '人脸识别运行库、模型或摄像头不可用。',
    };
}

sub identify_face {
    my ($params) = @_;
    my $frames = int($params->{frames} || 75);
    $frames = 20 if $frames < 20;
    $frames = 120 if $frames > 120;
    return busy_response() unless acquire_lock();
    release_camera();
    my $log = "$LOG_DIR/identify-last.log";
    my ($exit, $output) = run_face("recognize $frames", $log, 20);
    release_lock();

    my $match = best_match($output);
    if ($match->{accepted}) {
        return {
            ok => JSON::PP::true,
            status => 'matched',
            subject => $match->{subject},
            face_id => int($match->{face_id}),
            confidence => $match->{confidence} + 0,
            match_votes => int($match->{votes}),
            observed_matches => int($match->{observed}),
            captured_at => now_text(),
        };
    }
    my @unknown_scores = $output =~ /UNKNOWN\s+score=(-?[0-9.]+)/g;
    if (@unknown_scores) {
        @unknown_scores = sort { $b <=> $a } @unknown_scores;
        return {
            ok => JSON::PP::true,
            status => 'unknown',
            subject => undef,
            confidence => $match->{confidence} || $unknown_scores[0] + 0,
            match_votes => int($match->{votes} || 0),
            observed_matches => int($match->{observed} || 0),
            captured_at => now_text(),
        };
    }
    if ($match->{observed}) {
        return {
            ok => JSON::PP::true,
            status => 'unknown',
            subject => undef,
            confidence => $match->{confidence} + 0,
            match_votes => int($match->{votes} || 0),
            observed_matches => int($match->{observed}),
            error_message => '多帧结果不一致，请正对摄像头后重试。',
            captured_at => now_text(),
        };
    }
    if ($output =~ /no-face/ || $output =~ /faces=0/) {
        return {
            ok => JSON::PP::false,
            status => 'no_face',
            confidence => 0,
            error_message => '画面中未检测到清晰人脸，请正对摄像头后重试。',
            captured_at => now_text(),
        };
    }
    return {
        ok => JSON::PP::false,
        status => 'unavailable',
        confidence => 0,
        error_message => $exit == 124 ? '人脸识别超时。' : '人脸识别未返回有效结果。',
        detail => tail_text($output, 500),
        captured_at => now_text(),
    };
}

sub enroll_face {
    my ($params) = @_;
    my $subject = trim($params->{subject} || '');
    return { ok => JSON::PP::false, status => 'invalid_subject', error_message => '缺少有效的人脸主体标识。' }
        unless $subject =~ /^[A-Za-z0-9_.:-]{1,63}$/;
    my $samples = int($params->{samples} || 18);
    $samples = 10 if $samples < 10;
    $samples = 30 if $samples > 30;
    return busy_response() unless acquire_lock();
    release_camera();
    my $log = "$LOG_DIR/enroll-last.log";
    my ($exit, $output) = run_face('enroll ' . shell_quote($subject) . " $samples", $log, 45);
    release_lock();

    my @enrolled = $output =~ /Enrolled sample\s+(\d+)\/(\d+):/g;
    my $count = 0;
    while ($output =~ /Enrolled sample\s+(\d+)\/(\d+):/g) {
        $count = $1 if $1 > $count;
    }
    if ($exit == 0 && $count >= $samples) {
        return {
            ok => JSON::PP::true,
            status => 'enrolled',
            subject => $subject,
            samples => $count,
            enrolled_at => now_text(),
        };
    }
    my $message = $output =~ /Waiting for exactly one face/ || $output =~ /faces=0/
        ? '未持续检测到单张清晰人脸，请缓慢左右转头并保持在画面中央。'
        : '人脸录入未完成，请调整距离、光线并缓慢左右转头后重试。';
    return {
        ok => JSON::PP::false,
        status => 'enroll_failed',
        subject => $subject,
        samples => $count,
        error_message => $message,
        detail => tail_text($output, 500),
    };
}

sub list_faces {
    my $log = "$LOG_DIR/list-last.log";
    my ($exit, $output) = run_face('list', $log, 12);
    my ($count) = $output =~ /Feature records:\s*(\d+)/;
    my %subjects;
    while ($output =~ /id=\d+\s+name=([^\r\n]+)/g) {
        $subjects{trim($1)} = 1;
    }
    return {
        ok => $exit == 0 ? JSON::PP::true : JSON::PP::false,
        status => $exit == 0 ? 'available' : 'unavailable',
        sample_count => int($count || 0),
        subjects => [sort keys %subjects],
        error_message => $exit == 0 ? undef : '无法读取人脸库。',
    };
}

sub best_match {
    my ($output) = @_;
    my %groups;
    my $observed = 0;
    while ($output =~ /MATCH\s+name=(.+?)\s+id=(\d+)\s+score=([0-9.]+)/g) {
        my ($subject, $id, $score) = (trim($1), $2, $3 + 0);
        $observed++;
        push @{$groups{$subject}{scores}}, $score;
        if (!defined $groups{$subject}{best_score} || $score > $groups{$subject}{best_score}) {
            $groups{$subject}{best_score} = $score;
            $groups{$subject}{face_id} = $id;
        }
    }
    return { accepted => 0, observed => 0, votes => 0, confidence => 0 } unless $observed;

    my @ranked;
    for my $subject (keys %groups) {
        my @scores = @{$groups{$subject}{scores}};
        my $sum = 0;
        $sum += $_ for @scores;
        push @ranked, {
            subject => $subject,
            face_id => $groups{$subject}{face_id},
            votes => scalar @scores,
            average => $sum / scalar(@scores),
            best_score => $groups{$subject}{best_score},
        };
    }
    @ranked = sort {
        $b->{votes} <=> $a->{votes}
            || $b->{average} <=> $a->{average}
            || $b->{best_score} <=> $a->{best_score}
    } @ranked;
    my $best = $ranked[0];
    my $runner = $ranked[1];
    my $dominant = !$runner
        || $best->{votes} > $runner->{votes}
        || ($best->{average} - $runner->{average}) >= $VOTE_MARGIN;
    my $stable = $best->{votes} >= $MIN_MATCH_VOTES && $best->{average} >= $ACCEPT_THRESHOLD;
    my $strong = $best->{votes} >= 2 && $best->{average} >= 0.55;
    return {
        accepted => ($dominant && ($stable || $strong)) ? 1 : 0,
        observed => $observed,
        subject => $best->{subject},
        face_id => $best->{face_id},
        votes => $best->{votes},
        confidence => $best->{average},
    };
}

sub run_face {
    my ($arguments, $log, $timeout) = @_;
    my $command = 'cd ' . shell_quote($FACE_HOME) .
        ' && QSM_FACE_THRESHOLD=' . shell_quote($SEARCH_THRESHOLD) . ' ./face.sh ' . $arguments;
    my $rc;
    {
        local $SIG{CHLD} = 'DEFAULT';
        $rc = system('timeout', int($timeout), 'sh', '-c', $command . ' >' . shell_quote($log) . ' 2>&1');
    }
    my $exit = $rc == -1 ? -1 : ($rc >> 8);
    return ($exit, read_text($log));
}

sub release_camera {
    system('sh', '-c', 'wget -qO- --post-data="" ' . shell_quote("$MAIN_GATEWAY/api/camera/stream/stop") . ' >/dev/null 2>&1 || true');
    system('sh', '-c', shell_quote("$FACE_HOME/stop.sh") . ' >/dev/null 2>&1 || true');
    select(undef, undef, undef, 0.35);
}

sub acquire_lock {
    for (1 .. 30) {
        return 1 if mkdir $LOCK_DIR, 0750;
        select(undef, undef, undef, 0.1);
    }
    return 0;
}

sub release_lock {
    rmdir $LOCK_DIR if -d $LOCK_DIR;
}

sub busy_response {
    return { ok => JSON::PP::false, status => 'busy', error_message => '摄像头正在执行另一项任务，请稍后重试。' };
}

sub read_request {
    my ($client) = @_;
    my $first = <$client>;
    return undef unless defined $first;
    $first =~ s/\r?\n$//;
    my ($method, $target) = split /\s+/, $first;
    return undef unless $method && $target;
    my %headers;
    while (my $line = <$client>) {
        last if $line =~ /^\r?\n$/;
        $line =~ s/\r?\n$//;
        my ($key, $value) = split /:\s*/, $line, 2;
        $headers{lc $key} = $value if defined $key;
    }
    my $body = '';
    my $length = int($headers{'content-length'} || 0);
    read($client, $body, $length) if $length > 0;
    my ($path, $query) = split /\?/, $target, 2;
    my $params = parse_form($query || '');
    if ($body ne '') {
        if (($headers{'content-type'} || '') =~ /application\/json/) {
            my $decoded = eval { decode_json($body) };
            $params = $decoded if $decoded && ref($decoded) eq 'HASH';
        } else {
            $params = parse_form($body);
        }
    }
    return { method => uc($method), path => $path || '/', params => $params };
}

sub parse_form {
    my ($text) = @_;
    my %params;
    for my $pair (split /&/, $text || '') {
        my ($key, $value) = split /=/, $pair, 2;
        next unless defined $key;
        $params{url_decode($key)} = url_decode($value || '');
    }
    return \%params;
}

sub url_decode {
    my ($value) = @_;
    $value =~ tr/+/ /;
    $value =~ s/%([0-9A-Fa-f]{2})/chr(hex($1))/eg;
    return decode('UTF-8', $value);
}

sub send_json {
    my ($client, $status, $payload) = @_;
    my $body = encode_json($payload);
    my $reason = $status == 200 ? 'OK' : $status == 404 ? 'Not Found' : 'Internal Server Error';
    print {$client} "HTTP/1.1 $status $reason\r\n";
    print {$client} "Content-Type: application/json; charset=utf-8\r\n";
    print {$client} "Access-Control-Allow-Origin: *\r\n";
    print {$client} "Connection: close\r\n";
    print {$client} 'Content-Length: ' . length($body) . "\r\n\r\n";
    print {$client} $body;
}

sub shell_quote {
    my ($value) = @_;
    $value =~ s/'/'"'"'/g;
    return "'$value'";
}

sub read_text {
    my ($path) = @_;
    open my $file, '<:raw', $path or return '';
    local $/;
    my $text = <$file>;
    close $file;
    return defined $text ? $text : '';
}

sub tail_text {
    my ($text, $length) = @_;
    return length($text) > $length ? substr($text, -$length) : $text;
}

sub number_env {
    my ($name, $fallback) = @_;
    my $value = $ENV{$name};
    return $fallback unless defined $value && $value =~ /^\d+(?:\.\d+)?$/;
    return $value + 0;
}

sub trim {
    my ($value) = @_;
    $value = '' unless defined $value;
    $value =~ s/^\s+|\s+$//g;
    return $value;
}

sub now_text {
    return strftime('%Y-%m-%d %H:%M:%S', localtime);
}
