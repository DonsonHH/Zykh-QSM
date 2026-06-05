#!/usr/bin/env perl
use strict;
use warnings;
use utf8;
use IO::Socket::INET;
use JSON::PP qw(encode_json decode_json);
use POSIX qw(strftime setsid);
use File::Basename qw(dirname);
use File::Path qw(make_path);
use Cwd qw(abs_path);

$ENV{TZ} ||= 'CST-8';
eval { POSIX::tzset() };
use Encode qw(decode);

$| = 1;

my $HOME_DIR = $ENV{ZYKH_HOME} || dirname(abs_path($0));
my $WEB_DIR  = "$HOME_DIR/web";
my $DATA_DIR = "$HOME_DIR/data";
my $DB_FILE  = "$DATA_DIR/zykh.db";
my $PORT     = $ENV{PORT} || 8080;
my $DAEMON   = grep { $_ eq '--daemon' } @ARGV;

make_path($DATA_DIR) unless -d $DATA_DIR;
init_db();

daemonize() if $DAEMON;

my $server = IO::Socket::INET->new(
    LocalHost => '0.0.0.0',
    LocalPort => $PORT,
    Proto     => 'tcp',
    Listen    => 20,
    Reuse     => 1,
) or die "Cannot start server on port $PORT: $!\n";

print "ZYKH server listening on 0.0.0.0:$PORT\n";
print "Home: $HOME_DIR\n";

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
        my $req = read_request($client);
        if (!$req) {
            close $client;
            next;
        }
        route_request($client, $req);
    };
    if ($@) {
        send_json($client, 500, { ok => JSON::PP::false, error => "$@" });
    }
    close $client;
    exit 0;
}

sub now_text {
    return strftime('%Y-%m-%d %H:%M:%S', localtime);
}

sub daemonize {
    my $pid = fork();
    die "fork failed: $!\n" unless defined $pid;
    if ($pid) {
        print "ZYKH server daemon pid: $pid\n";
        exit 0;
    }
    setsid();
    chdir $HOME_DIR or die "chdir failed: $!\n";
    open STDIN,  '<', '/dev/null' or die "redirect stdin failed: $!\n";
    open STDOUT, '>>', "$HOME_DIR/server.log" or die "redirect stdout failed: $!\n";
    open STDERR, '>>', "$HOME_DIR/server.log" or die "redirect stderr failed: $!\n";
}

sub init_db {
    sqlite_exec(<<'SQL');
CREATE TABLE IF NOT EXISTS medicines (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  slot INTEGER NOT NULL,
  dosage TEXT DEFAULT '',
  stock INTEGER DEFAULT 0,
  expire_date TEXT DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS plans (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  medicine_id INTEGER NOT NULL,
  time TEXT NOT NULL,
  amount TEXT DEFAULT '1片',
  enabled INTEGER DEFAULT 1,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS records (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  medicine_name TEXT NOT NULL,
  slot INTEGER,
  action TEXT NOT NULL,
  result TEXT NOT NULL,
  detail TEXT DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS patient_profile (
  id INTEGER PRIMARY KEY CHECK(id = 1),
  name TEXT DEFAULT '',
  gender TEXT DEFAULT '',
  age INTEGER DEFAULT 0,
  height TEXT DEFAULT '',
  weight TEXT DEFAULT '',
  conditions TEXT DEFAULT '',
  allergies TEXT DEFAULT '',
  notes TEXT DEFAULT '',
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS vitals_records (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  temperature REAL,
  heart_rate INTEGER,
  spo2 INTEGER,
  systolic INTEGER,
  diastolic INTEGER,
  source TEXT DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS medicine_catalog (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  code TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL,
  dosage TEXT DEFAULT '',
  manufacturer TEXT DEFAULT '',
  batch_no TEXT DEFAULT '',
  expire_date TEXT DEFAULT '',
  trace_code TEXT DEFAULT '',
  note TEXT DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS health_memories (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  type TEXT DEFAULT 'case',
  title TEXT NOT NULL,
  content TEXT NOT NULL,
  happened_at TEXT DEFAULT '',
  source TEXT DEFAULT '',
  created_at TEXT NOT NULL
);
SQL

    my ($profile_count) = sqlite_row('SELECT COUNT(*) FROM patient_profile;');
    if (!defined $profile_count || $profile_count == 0) {
        sqlite_exec('INSERT INTO patient_profile(id,name,gender,age,height,weight,conditions,allergies,notes,updated_at) VALUES (' .
            join(',', 1, sql_quote('演示用户'), sql_quote('男'), 72, sql_quote('170cm'), sql_quote('68kg'),
                sql_quote('高血压；2型糖尿病；冠心病'), sql_quote('青霉素过敏'), sql_quote('家庭康护演示用户，可按实际老人信息修改'), sql_quote(now_text())) .
            ');');
    }

    my $now = sql_quote(now_text());
    my ($catalog_count) = sqlite_row('SELECT COUNT(*) FROM medicine_catalog;');
    if (!defined $catalog_count || $catalog_count == 0) {
        sqlite_exec("INSERT OR IGNORE INTO medicine_catalog(code,name,dosage,manufacturer,batch_no,expire_date,trace_code,note,created_at) VALUES " .
            "('6901234567890','硝苯地平片','10mg*30片','示例药业','B20260501','2026-12-31','TRACE6901234567890','演示条码，可替换为真实药品目录', $now)," .
            "('6971234567891','阿司匹林肠溶片','100mg*30片','示例制药','A20260412','2026-10-31','TRACE6971234567891','演示条码，可替换为真实药品目录', $now)," .
            "('6941234567892','二甲双胍片','500mg*60片','示例药厂','M20270108','2027-03-31','TRACE6941234567892','演示条码，可替换为真实药品目录', $now);");
    }

    my ($count) = sqlite_row('SELECT COUNT(*) FROM medicines;');
    return if defined $count && $count > 0;

    sqlite_exec("INSERT INTO medicines(name, slot, dosage, stock, expire_date, created_at) VALUES " .
        "('硝苯地平片', 1, '10mg*30片', 18, '2026-12-31', $now)," .
        "('阿司匹林肠溶片', 2, '100mg*30片', 8, '2026-10-31', $now)," .
        "('二甲双胍片', 3, '500mg*60片', 26, '2027-03-31', $now);");
    sqlite_exec("INSERT INTO plans(medicine_id, time, amount, enabled, created_at) VALUES " .
        "(1, '10:00', '1片', 1, $now)," .
        "(2, '14:00', '1片', 1, $now)," .
        "(3, '20:00', '1片', 1, $now);");

}

sub sqlite_exec {
    my ($sql) = @_;
    open my $fh, '|-', 'sqlite3', $DB_FILE or die "open sqlite3 failed: $!";
    binmode $fh, ':encoding(UTF-8)';
    print {$fh} $sql;
    close $fh;
}

sub sqlite_rows {
    my ($sql) = @_;
    open my $fh, '-|', 'sqlite3', '-separator', "\t", '-noheader', $DB_FILE, $sql
        or die "query sqlite3 failed: $!";
    binmode $fh, ':encoding(UTF-8)';
    my @rows;
    while (my $line = <$fh>) {
        chomp $line;
        push @rows, [split /\t/, $line, -1];
    }
    close $fh;
    return @rows;
}

sub sqlite_row {
    my ($sql) = @_;
    my @rows = sqlite_rows($sql);
    return @{$rows[0] || []};
}

sub sql_quote {
    my ($v) = @_;
    $v = '' unless defined $v;
    $v =~ s/'/''/g;
    return "'$v'";
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
        my ($k, $v) = split /:\s*/, $line, 2;
        $headers{lc $k} = $v if defined $k;
    }

    my $body = '';
    my $len = $headers{'content-length'} || 0;
    read($client, $body, $len) if $len > 0;

    my ($path, $query) = split /\?/, $target, 2;
    return {
        method  => uc($method),
        target  => $target,
        path    => clean_path($path || '/'),
        query   => parse_form($query || ''),
        headers => \%headers,
        body    => $body,
        params  => parse_body(\%headers, $body),
    };
}

sub clean_path {
    my ($path) = @_;
    $path =~ s/%([0-9A-Fa-f]{2})/chr(hex($1))/eg;
    $path =~ s#/{2,}#/#g;
    $path =~ s#\.\.##g;
    return $path || '/';
}

sub parse_body {
    my ($headers, $body) = @_;
    return {} unless defined $body && length $body;
    my $type = $headers->{'content-type'} || '';
    if ($type =~ /application\/json/) {
        my $obj = eval { decode_json($body) };
        return $obj if $obj && ref $obj eq 'HASH';
        return {};
    }
    return parse_form($body);
}

sub parse_form {
    my ($text) = @_;
    my %out;
    return \%out unless defined $text && length $text;
    for my $pair (split /&/, $text) {
        my ($k, $v) = split /=/, $pair, 2;
        next unless defined $k;
        $out{url_decode($k)} = url_decode($v // '');
    }
    return \%out;
}

sub url_decode {
    my ($s) = @_;
    $s =~ tr/+/ /;
    $s =~ s/%([0-9A-Fa-f]{2})/chr(hex($1))/eg;
    return decode('UTF-8', $s);
}

sub route_request {
    my ($client, $req) = @_;
    my $path = $req->{path};

    if ($path =~ m#^/api/#) {
        return route_api($client, $req);
    }

    $path = '/index.html' if $path eq '/';
    return serve_static($client, "$WEB_DIR$path");
}

sub route_api {
    my ($client, $req) = @_;
    my $path   = $req->{path};
    my $method = $req->{method};

    if ($method eq 'GET' && $path eq '/api/status') {
        return send_json($client, 200, api_status());
    }
    if ($method eq 'GET' && $path eq '/api/medicines') {
        return send_json($client, 200, { ok => JSON::PP::true, medicines => list_medicines() });
    }
    if ($method eq 'POST' && $path eq '/api/medicines') {
        return send_json($client, 200, add_medicine($req->{params}));
    }
    if ($method eq 'GET' && $path eq '/api/medicine/lookup') {
        return send_json($client, 200, lookup_medicine($req->{query}));
    }
    if ($method eq 'POST' && $path eq '/api/medicine/scan') {
        return send_json($client, 200, scan_medicine_code($req->{params}));
    }
    if ($method eq 'POST' && $path eq '/api/medicine/auto_add') {
        return send_json($client, 200, auto_add_medicine($req->{params}));
    }
    if ($method eq 'GET' && $path eq '/api/memories') {
        return send_json($client, 200, { ok => JSON::PP::true, memories => list_memories() });
    }
    if ($method eq 'POST' && $path eq '/api/memories') {
        return send_json($client, 200, add_memory($req->{params}));
    }
    if ($method eq 'GET' && $path eq '/api/plans') {
        return send_json($client, 200, { ok => JSON::PP::true, plans => list_plans() });
    }
    if ($method eq 'POST' && $path eq '/api/plans') {
        return send_json($client, 200, add_plan($req->{params}));
    }
    if ($method eq 'GET' && $path eq '/api/records') {
        return send_json($client, 200, { ok => JSON::PP::true, records => list_records() });
    }
    if ($method eq 'GET' && $path eq '/api/profile') {
        return send_json($client, 200, { ok => JSON::PP::true, profile => get_profile() });
    }
    if ($method eq 'POST' && $path eq '/api/profile') {
        return send_json($client, 200, save_profile($req->{params}));
    }
    if ($method eq 'GET' && $path eq '/api/vitals') {
        return send_json($client, 200, { ok => JSON::PP::true, vitals => list_vitals() });
    }
    if ($method eq 'POST' && $path eq '/api/vitals') {
        return send_json($client, 200, add_vitals($req->{params}));
    }
    if ($method eq 'POST' && $path eq '/api/dispense') {
        return send_json($client, 200, dispense($req->{params}));
    }
    if ($method eq 'POST' && $path eq '/api/gpio') {
        return send_json($client, 200, gpio_set($req->{params}));
    }
    if ($method eq 'POST' && $path eq '/api/vitals/read') {
        return send_json($client, 200, read_vitals());
    }
    if ($method eq 'POST' && $path eq '/api/recognize') {
        return send_json($client, 200, recognize_medicine());
    }
    if ($method eq 'POST' && $path eq '/api/camera/capture') {
        return send_json($client, 200, capture_camera());
    }
    if ($method eq 'GET' && $path eq '/api/camera/frame') {
        return send_camera_frame($client);
    }
    if ($method eq 'GET' && $path eq '/api/camera/stream') {
        return send_mjpeg_stream($client, $req->{query});
    }
    if ($method eq 'POST' && $path eq '/api/camera/stream/stop') {
        return send_json($client, 200, stop_camera_stream_producer());
    }
    if ($method eq 'POST' && $path eq '/api/camera/preview/start') {
        return send_json($client, 200, start_camera_preview($req->{params}));
    }
    if ($method eq 'POST' && $path eq '/api/camera/preview/stop') {
        return send_json($client, 200, stop_camera_preview());
    }
    if ($method eq 'POST' && $path eq '/api/ai/chat') {
        return send_json($client, 200, ai_chat($req->{params}));
    }
    if ($method eq 'POST' && $path eq '/api/ai/chat/stream') {
        return send_ai_chat_stream($client, $req->{params});
    }
    if ($method eq 'POST' && $path eq '/api/audio/record') {
        return send_json($client, 200, record_audio($req->{params}));
    }
    if ($method eq 'POST' && $path eq '/api/audio/speak') {
        return send_json($client, 200, speak_text($req->{params}));
    }

    return send_json($client, 404, { ok => JSON::PP::false, error => 'API not found' });
}

sub api_status {
    my $hostname = trim(`hostname 2>/dev/null`);
    my $arch     = trim(`uname -m 2>/dev/null`);
    my $uptime   = trim(`cut -d' ' -f1 /proc/uptime 2>/dev/null`);
    my $os       = 'Buildroot';
    if (open my $fh, '<', '/etc/os-release') {
        while (my $line = <$fh>) {
            if ($line =~ /^PRETTY_NAME="?([^"\n]+)"?/) {
                $os = $1;
                last;
            }
        }
        close $fh;
    }

    return {
        ok       => JSON::PP::true,
        hostname => $hostname,
        arch     => $arch,
        os       => $os,
        uptime   => $uptime + 0,
        time     => now_text(),
        devices  => {
            video => [map { basename($_) } glob('/dev/video*')],
            i2c   => [map { basename($_) } glob('/dev/i2c-*')],
            uart  => [map { basename($_) } glob('/dev/ttyS*')],
            pwm   => [map { basename($_) } glob('/sys/class/pwm/pwmchip*')],
        },
    };
}

sub list_medicines {
    my @rows = sqlite_rows('SELECT id,name,slot,dosage,stock,expire_date,created_at FROM medicines ORDER BY slot, id;');
    return [map {
        {
            id => $_->[0] + 0, name => $_->[1], slot => $_->[2] + 0,
            dosage => $_->[3], stock => $_->[4] + 0, expire_date => $_->[5],
            created_at => $_->[6],
        }
    } @rows];
}

sub add_medicine {
    my ($p) = @_;
    my $name = $p->{name} || '';
    my $slot = int($p->{slot} || 0);
    return { ok => JSON::PP::false, error => '药品名称和仓位必填' } if $name eq '' || $slot <= 0;
    my $dosage = $p->{dosage} || '';
    my $stock  = int($p->{stock} || 0);
    my $expire = $p->{expire_date} || '';
    sqlite_exec('INSERT INTO medicines(name,slot,dosage,stock,expire_date,created_at) VALUES (' .
        join(',', map { sql_quote($_) } ($name, $slot, $dosage, $stock, $expire, now_text())) . ');');
    return { ok => JSON::PP::true, medicines => list_medicines() };
}

sub lookup_medicine {
    my ($p) = @_;
    my $code = normalize_code($p->{code} || $p->{trace_code} || '');
    return { ok => JSON::PP::false, error => '未识别到条形码或溯源码' } if $code eq '';
    my @row = sqlite_row('SELECT code,name,dosage,manufacturer,batch_no,expire_date,trace_code,note FROM medicine_catalog WHERE code=' . sql_quote($code) . ' OR trace_code=' . sql_quote($code) . ' LIMIT 1;');
    if (!@row) {
        return {
            ok => JSON::PP::true,
            found => JSON::PP::false,
            code => $code,
            detail => '本地药品目录未收录该条码，请人工核对后录入，后续可接入药监码/企业追溯接口或导入本地目录。',
        };
    }
    return {
        ok => JSON::PP::true,
        found => JSON::PP::true,
        medicine => {
            code => $row[0], name => $row[1], dosage => $row[2], manufacturer => $row[3],
            batch_no => $row[4], expire_date => $row[5], trace_code => $row[6], note => $row[7],
        },
    };
}

sub auto_add_medicine {
    my ($p) = @_;
    my $lookup = lookup_medicine($p);
    return $lookup unless $lookup->{ok};
    return $lookup unless $lookup->{found};
    my $m = $lookup->{medicine};
    my $slot = int($p->{slot} || first_empty_slot());
    my $stock = int($p->{stock} || 1);
    sqlite_exec('INSERT INTO medicines(name,slot,dosage,stock,expire_date,created_at) VALUES (' .
        join(',', map { sql_quote($_) } ($m->{name}, $slot, $m->{dosage}, $stock, $m->{expire_date}, now_text())) . ');');
    add_record($m->{name}, $slot, 'medicine_auto_add', 'success', '条码/溯源码自动录入：' . ($m->{code} || $m->{trace_code} || ''));
    return { ok => JSON::PP::true, found => JSON::PP::true, medicine => $m, slot => $slot, medicines => list_medicines() };
}

sub scan_medicine_code {
    my ($p) = @_;
    my $capture = capture_camera();
    return $capture unless $capture->{ok};

    my $image = "$WEB_DIR/camera/latest.jpg";
    my $code = '';
    my $scanner = '';
    my $detail = '';

    my $decoded = decode_medicine_image($image);
    if ($decoded->{ok}) {
        $code = normalize_code($decoded->{code});
        $scanner = $decoded->{scanner};
        $detail = '已从摄像头图像识别到条码/溯源码，格式：' . ($decoded->{format} || 'unknown');
    }

    if ($code eq '' && trim(`which zbarimg 2>/dev/null`) ne '') {
        my $log = "$DATA_DIR/medicine-scan.log";
        my $cmd = 'zbarimg --raw ' . shell_quote($image) . ' >' . shell_quote($log) . ' 2>&1';
        my $rc;
        {
            local $SIG{CHLD} = 'DEFAULT';
            $rc = system('timeout', '8', 'sh', '-c', $cmd);
        }
        my $raw = read_text_file($log);
        ($code) = grep { $_ ne '' } map { normalize_code($_) } split(/\r?\n/, $raw || '');
        $scanner = 'zbarimg';
        $detail = $code ? '已从摄像头图像识别到条码/溯源码' : '未从图像中识别到条码/溯源码';
    }

    if ($code eq '') {
        $code = normalize_code($p->{code} || $p->{trace_code} || $ENV{DEMO_TRACE_CODE} || 'TRACE6901234567890');
        $scanner = 'demo-no-zbar';
        $detail = $decoded->{error} || '板端当前没有可用条码解码器，使用演示溯源码跑通扫码、查目录、自动录入流程；部署 zykh-scan-code 或安装 zbar 后可替换为真实图像解码。';
    }

    my $lookup = lookup_medicine({ code => $code });
    return {
        ok => JSON::PP::true,
        code => $code,
        scanner => $scanner,
        detail => $detail,
        image_url => $capture->{image_url},
        lookup => $lookup,
    };
}

sub decode_medicine_image {
    my ($image) = @_;
    my @candidates;
    push @candidates, $ENV{BARCODE_DECODER} if $ENV{BARCODE_DECODER};
    push @candidates, "$HOME_DIR/bin/zykh-scan-code";

    for my $decoder (@candidates) {
        next unless $decoder && -x $decoder;
        my $log = "$DATA_DIR/medicine-scan-code.log";
        my $cmd = shell_quote($decoder) . ' -json ' . shell_quote($image) . ' >' . shell_quote($log) . ' 2>&1';
        my $rc;
        {
            local $SIG{CHLD} = 'DEFAULT';
            $rc = system('timeout', '8', 'sh', '-c', $cmd);
        }
        my $raw = read_text_file($log);
        my $obj = eval { decode_json($raw || '') };
        if ($obj && $obj->{ok} && normalize_code($obj->{code}) ne '') {
            return {
                ok => JSON::PP::true,
                code => normalize_code($obj->{code}),
                format => $obj->{format} || '',
                scanner => basename($decoder),
            };
        }
        my $exit = $rc == -1 ? -1 : ($rc >> 8);
        return {
            ok => JSON::PP::false,
            error => '真实扫码未识别到条码/二维码：' . substr(($obj && $obj->{error}) || $raw || "exit=$exit", 0, 160),
            scanner => basename($decoder),
        };
    }

    return { ok => JSON::PP::false, error => '没有找到 zykh-scan-code 或 zbarimg 解码器' };
}

sub first_empty_slot {
    my %used = map { $_->{slot} => 1 } @{list_medicines()};
    for my $slot (1..23) {
        return $slot unless $used{$slot};
    }
    return 23;
}

sub normalize_code {
    my ($code) = @_;
    $code = trim($code || '');
    if ($code =~ /[?&](?:code|barcode|traceCode|trace_code)=([^&]+)/i) {
        $code = url_decode($1);
    }
    $code =~ s/^\s+|\s+$//g;
    return $code;
}

sub record_audio {
    my ($p) = @_;
    my $duration = int($p->{duration} || 3);
    $duration = 1 if $duration < 1;
    $duration = 8 if $duration > 8;
    my $dir = "$DATA_DIR/audio";
    make_path($dir) unless -d $dir;
    my $out = "$dir/last-question.wav";
    my $log = "$DATA_DIR/audio-record.log";
    unlink $out if -e $out;

    my $device = $ENV{AUDIO_CAPTURE_DEVICE} || 'plughw:0,0';
    my $cmd = 'arecord -q -D ' . shell_quote($device) . ' -f S16_LE -r 16000 -c 1 -d ' . int($duration) . ' ' . shell_quote($out);
    my $run = $cmd . ' >' . shell_quote($log) . ' 2>&1';
    my $rc;
    {
        local $SIG{CHLD} = 'DEFAULT';
        $rc = system('timeout', int($duration) + 3, 'sh', '-c', $run);
    }
    my $exit = $rc == -1 ? -1 : ($rc >> 8);
    if (-s $out) {
        return {
            ok => JSON::PP::true,
            file => "$dir/last-question.wav",
            duration => $duration,
            device => $device,
            detail => '麦克风录音完成；后续可接 RKNN Whisper 做语音转文字。',
            exit_code => $exit,
        };
    }
    my $err = read_text_file($log);
    return {
        ok => JSON::PP::false,
        error => '麦克风录音失败',
        detail => substr($err || '', 0, 500),
        command => $cmd,
        exit_code => $exit,
    };
}

sub speak_text {
    my ($p) = @_;
    my $text = trim($p->{text} || '');
    return { ok => JSON::PP::false, error => '播报文本为空' } if $text eq '';
    $text = substr($text, 0, 500);

    my $dir = "$DATA_DIR/audio";
    make_path($dir) unless -d $dir;
    my $log = "$DATA_DIR/audio-speak.log";
    my $cmd = '';
    my $mode = '';

    if ($ENV{TTS_CMD}) {
        $cmd = $ENV{TTS_CMD};
        $cmd =~ s/\{text\}/shell_quote($text)/eg;
        $mode = 'custom-tts';
    } elsif (trim(`which espeak 2>/dev/null`) ne '') {
        $cmd = 'espeak -v zh -s 145 ' . shell_quote($text);
        $mode = 'espeak';
    } elsif (trim(`which flite 2>/dev/null`) ne '') {
        my $out = "$dir/tts.wav";
        $cmd = 'flite -t ' . shell_quote($text) . ' -o ' . shell_quote($out) . ' && ' . aplay_cmd($out);
        $mode = 'flite';
    } elsif (trim(`which aplay 2>/dev/null`) ne '') {
        my $tone = "$dir/tts-notice.wav";
        write_notice_wav($tone);
        $cmd = aplay_cmd($tone);
        $mode = 'notice-tone';
    } else {
        return { ok => JSON::PP::false, error => '板端未找到 TTS 或 aplay 播放命令', mode => 'none' };
    }

    my $rc;
    {
        local $SIG{CHLD} = 'DEFAULT';
        $rc = system('timeout', '20', 'sh', '-c', $cmd . ' >' . shell_quote($log) . ' 2>&1');
    }
    my $exit = $rc == -1 ? -1 : ($rc >> 8);
    my $ok = $exit == 0 ? JSON::PP::true : JSON::PP::false;
    my $detail = $mode eq 'notice-tone'
        ? '当前板端缺少中文 TTS 引擎，已用喇叭提示音验证播放链路；后续设置 TTS_CMD 可替换为真实语音合成。'
        : '语音播报命令已执行。';
    return {
        ok => $ok,
        mode => $mode,
        detail => $ok ? $detail : '语音播报失败：' . substr(read_text_file($log) || '', 0, 300),
        exit_code => $exit,
    };
}

sub aplay_cmd {
    my ($file) = @_;
    my $device = $ENV{AUDIO_PLAY_DEVICE} || 'plughw:0,0';
    return 'aplay -q -D ' . shell_quote($device) . ' ' . shell_quote($file);
}

sub write_notice_wav {
    my ($file) = @_;
    my $rate = 16000;
    my $samples = int($rate * 0.42);
    my $data = '';
    my $pi = 3.141592653589793;
    for my $i (0 .. $samples - 1) {
        my $freq = $i < $samples / 2 ? 880 : 1174;
        my $amp = int(9000 * sin(2 * $pi * $freq * $i / $rate));
        $amp += 65536 if $amp < 0;
        $data .= pack('v', $amp);
    }
    my $data_len = length($data);
    my $header = 'RIFF' . pack('V', 36 + $data_len) . 'WAVEfmt ' .
        pack('VvvVVvv', 16, 1, 1, $rate, $rate * 2, 2, 16) .
        'data' . pack('V', $data_len);
    write_raw_file($file, $header . $data);
}

sub list_memories {
    my @rows = sqlite_rows("SELECT id,type,title,content,happened_at,source,created_at FROM health_memories ORDER BY COALESCE(NULLIF(happened_at, ''), created_at) DESC, id DESC LIMIT 50;");
    return [map {
        {
            id => $_->[0] + 0,
            type => $_->[1] || 'case',
            title => $_->[2] || '',
            content => $_->[3] || '',
            happened_at => $_->[4] || '',
            source => $_->[5] || '',
            created_at => $_->[6] || '',
        }
    } @rows];
}

sub add_memory {
    my ($p) = @_;
    my $title = trim($p->{title} || '');
    my $content = trim($p->{content} || '');
    return { ok => JSON::PP::false, error => '标题和内容必填' } if $title eq '' || $content eq '';
    sqlite_exec('INSERT INTO health_memories(type,title,content,happened_at,source,created_at) VALUES (' .
        join(',',
            sql_quote($p->{type} || 'case'),
            sql_quote($title),
            sql_quote($content),
            sql_quote($p->{happened_at} || ''),
            sql_quote($p->{source} || 'manual'),
            sql_quote(now_text())) .
        ');');
    return { ok => JSON::PP::true, memories => list_memories() };
}

sub list_plans {
    my @rows = sqlite_rows(<<'SQL');
SELECT plans.id, medicines.name, medicines.slot, plans.time, plans.amount, plans.enabled, plans.created_at
FROM plans
LEFT JOIN medicines ON medicines.id = plans.medicine_id
ORDER BY plans.time, plans.id;
SQL
    return [map {
        {
            id => $_->[0] + 0, medicine_name => $_->[1] || '未知药品',
            slot => ($_->[2] || 0) + 0, time => $_->[3], amount => $_->[4],
            enabled => ($_->[5] || 0) + 0, created_at => $_->[6],
        }
    } @rows];
}

sub add_plan {
    my ($p) = @_;
    my $medicine_id = int($p->{medicine_id} || 0);
    my $time = $p->{time} || '';
    my $amount = $p->{amount} || '1片';
    return { ok => JSON::PP::false, error => '药品和时间必填' } if $medicine_id <= 0 || $time !~ /^\d\d:\d\d$/;
    sqlite_exec('INSERT INTO plans(medicine_id,time,amount,enabled,created_at) VALUES (' .
        join(',', $medicine_id, sql_quote($time), sql_quote($amount), 1, sql_quote(now_text())) . ');');
    return { ok => JSON::PP::true, plans => list_plans() };
}

sub list_records {
    my @rows = sqlite_rows('SELECT id,medicine_name,slot,action,result,detail,created_at FROM records ORDER BY id DESC LIMIT 30;');
    return [map {
        {
            id => $_->[0] + 0, medicine_name => $_->[1],
            slot => ($_->[2] || 0) + 0, action => $_->[3],
            result => $_->[4], detail => $_->[5], created_at => $_->[6],
        }
    } @rows];
}

sub get_profile {
    my @row = sqlite_row('SELECT name,gender,age,height,weight,conditions,allergies,notes,updated_at FROM patient_profile WHERE id=1;');
    return {
        name => $row[0] || '',
        gender => $row[1] || '',
        age => ($row[2] || 0) + 0,
        height => $row[3] || '',
        weight => $row[4] || '',
        conditions => $row[5] || '',
        allergies => $row[6] || '',
        notes => $row[7] || '',
        updated_at => $row[8] || '',
    };
}

sub save_profile {
    my ($p) = @_;
    my $age = int($p->{age} || 0);
    sqlite_exec('INSERT OR REPLACE INTO patient_profile(id,name,gender,age,height,weight,conditions,allergies,notes,updated_at) VALUES (' .
        join(',', 1,
            sql_quote($p->{name} || ''),
            sql_quote($p->{gender} || ''),
            $age,
            sql_quote($p->{height} || ''),
            sql_quote($p->{weight} || ''),
            sql_quote($p->{conditions} || ''),
            sql_quote($p->{allergies} || ''),
            sql_quote($p->{notes} || ''),
            sql_quote(now_text())) .
        ');');
    return { ok => JSON::PP::true, profile => get_profile() };
}

sub list_vitals {
    my @rows = sqlite_rows('SELECT id,temperature,heart_rate,spo2,systolic,diastolic,source,created_at FROM vitals_records ORDER BY id DESC LIMIT 20;');
    return [map {
        {
            id => $_->[0] + 0,
            temperature => ($_->[1] || 0) + 0,
            heart_rate => ($_->[2] || 0) + 0,
            spo2 => ($_->[3] || 0) + 0,
            systolic => ($_->[4] || 0) + 0,
            diastolic => ($_->[5] || 0) + 0,
            source => $_->[6] || '',
            created_at => $_->[7] || '',
        }
    } @rows];
}

sub add_vitals {
    my ($p) = @_;
    my $temperature = $p->{temperature} || '';
    my $heart_rate = int($p->{heart_rate} || 0);
    my $spo2 = int($p->{spo2} || 0);
    my $systolic = int($p->{systolic} || 0);
    my $diastolic = int($p->{diastolic} || 0);
    my $source = $p->{source} || 'manual';
    sqlite_exec('INSERT INTO vitals_records(temperature,heart_rate,spo2,systolic,diastolic,source,created_at) VALUES (' .
        join(',',
            sql_quote($temperature),
            $heart_rate,
            $spo2,
            $systolic,
            $diastolic,
            sql_quote($source),
            sql_quote(now_text())) .
        ');');
    return { ok => JSON::PP::true, vitals => list_vitals() };
}

sub add_record {
    my ($name, $slot, $action, $result, $detail) = @_;
    sqlite_exec('INSERT INTO records(medicine_name,slot,action,result,detail,created_at) VALUES (' .
        join(',', map { sql_quote($_) } ($name, $slot, $action, $result, $detail || '', now_text())) . ');');
}

sub dispense {
    my ($p) = @_;
    my $slot = int($p->{slot} || 0);
    return { ok => JSON::PP::false, error => '仓位必填' } if $slot <= 0;

    my @med = sqlite_row('SELECT id,name,stock FROM medicines WHERE slot=' . int($slot) . ' ORDER BY id LIMIT 1;');
    my $name = $med[1] || "仓位$slot";
    my $stock = defined $med[2] ? int($med[2]) : -1;
    my $gpio = $ENV{"SLOT${slot}_GPIO"};
    $gpio = 27 if !defined $gpio && $slot == 1;

    my $detail;
    my $result = 'success';
    if (defined $gpio && $gpio =~ /^\d+$/) {
        my $r = pulse_gpio($gpio, 500);
        if ($r->{ok}) {
            $detail = "GPIO$gpio 已输出 500ms 出药控制脉冲";
        } else {
            $result = 'failed';
            $detail = $r->{error};
        }
    } else {
        $detail = '未配置真实 GPIO/PWM，已按模拟出药记录';
    }

    if ($result eq 'success' && $stock > 0 && defined $med[0]) {
        sqlite_exec('UPDATE medicines SET stock=stock-1 WHERE id=' . int($med[0]) . ';');
    }
    add_record($name, $slot, 'dispense', $result, $detail);
    return {
        ok => ($result eq 'success' ? JSON::PP::true : JSON::PP::false),
        result => $result,
        detail => $detail,
        records => list_records(),
        medicines => list_medicines(),
    };
}

sub gpio_set {
    my ($p) = @_;
    my $gpio = int($p->{gpio} || -1);
    my $value = int($p->{value} || 0) ? 1 : 0;
    return { ok => JSON::PP::false, error => 'GPIO 编号不合法' } if $gpio < 0;
    my $r = prepare_gpio($gpio, 'out');
    return $r unless $r->{ok};
    return write_gpio($gpio, $value);
}

sub pulse_gpio {
    my ($gpio, $ms) = @_;
    my $r = prepare_gpio($gpio, 'out');
    return $r unless $r->{ok};
    $r = write_gpio($gpio, 1);
    return $r unless $r->{ok};
    select(undef, undef, undef, ($ms || 500) / 1000);
    return write_gpio($gpio, 0);
}

sub prepare_gpio {
    my ($gpio, $direction) = @_;
    if (!-d "/sys/class/gpio/gpio$gpio") {
        if (open my $ex, '>', '/sys/class/gpio/export') {
            print {$ex} $gpio;
            close $ex;
            select(undef, undef, undef, 0.1);
        }
    }
    my $dir = "/sys/class/gpio/gpio$gpio/direction";
    return { ok => JSON::PP::false, error => "GPIO$gpio 不存在或无法导出" } unless -e $dir;
    if (open my $fh, '>', $dir) {
        print {$fh} $direction;
        close $fh;
        return { ok => JSON::PP::true };
    }
    return { ok => JSON::PP::false, error => "GPIO$gpio direction 写入失败: $!" };
}

sub write_gpio {
    my ($gpio, $value) = @_;
    my $path = "/sys/class/gpio/gpio$gpio/value";
    if (open my $fh, '>', $path) {
        print {$fh} $value ? '1' : '0';
        close $fh;
        return { ok => JSON::PP::true, gpio => $gpio, value => $value };
    }
    return { ok => JSON::PP::false, error => "GPIO$gpio value 写入失败: $!" };
}

sub read_vitals {
    my $sec = time % 60;
    my $vitals = {
        temperature => sprintf('%.1f', 36.4 + (($sec % 5) * 0.1)) + 0,
        heart_rate  => 72 + ($sec % 9),
        spo2        => 96 + ($sec % 3),
        systolic    => 136 + ($sec % 6),
        diastolic   => 82 + ($sec % 5),
        source      => 'demo',
        time        => now_text(),
    };
    add_vitals({
        temperature => $vitals->{temperature},
        heart_rate => $vitals->{heart_rate},
        spo2 => $vitals->{spo2},
        systolic => $vitals->{systolic},
        diastolic => $vitals->{diastolic},
        source => $vitals->{source},
    });
    return {
        ok => JSON::PP::true,
        vitals => $vitals,
    };
}

sub recognize_medicine {
    return {
        ok => JSON::PP::true,
        recognition => {
            name => '硝苯地平片',
            confidence => 0.86,
            source => 'demo',
            note => '摄像头和 RKNN 模型接入后替换此接口',
            time => now_text(),
        },
    };
}

sub capture_camera {
    stop_camera_stream_producer();
    select(undef, undef, undef, 0.5);
    my $camera_dir = "$WEB_DIR/camera";
    make_path($camera_dir) unless -d $camera_dir;
    my $out = "$camera_dir/latest.jpg";
    unlink $out if -e $out;

    my $cmd = $ENV{CAMERA_CAPTURE_CMD};
    if ($cmd && $cmd =~ /\{out\}/) {
        $cmd =~ s/\{out\}/shell_quote($out)/eg;
    } elsif ($cmd) {
        $cmd .= ' ' . shell_quote($out);
    } else {
        my $device = detect_camera_device();
        $cmd = 'gst-launch-1.0 -q v4l2src device=' . shell_quote($device) . ' num-buffers=5 ' .
               '! video/x-raw,format=NV12,width=640,height=480,framerate=30/1 ' .
               '! videoconvert ! jpegenc ! filesink location=' . shell_quote($out);
    }

    my $logfile = "$DATA_DIR/camera-capture.log";
    my $run_cmd = $cmd . ' >' . shell_quote($logfile) . ' 2>&1';
    my $rc;
    {
        local $SIG{CHLD} = 'DEFAULT';
        $rc = system('timeout', '8', 'sh', '-c', $run_cmd);
    }
    my $exit = $rc == -1 ? -1 : ($rc >> 8);
    my $signal = $rc == -1 ? 0 : ($rc & 127);
    if (-s $out) {
        return {
            ok => JSON::PP::true,
            image_url => '/camera/latest.jpg',
            detail => '摄像头拍照完成',
            command => $cmd,
            exit_code => $exit,
            signal => $signal,
        };
    }

    my $log = read_text_file($logfile);
    $log = substr($log, -1200) if defined $log && length($log) > 1200;
    return {
        ok => JSON::PP::false,
        error => '摄像头拍照失败，请检查 CAMERA_CAPTURE_CMD 或 /dev/video-camera0',
        command => $cmd,
        exit_code => $exit,
        signal => $signal,
        log => $log || '',
    };
}

sub send_camera_frame {
    my ($client) = @_;
    my $camera_dir = "$WEB_DIR/camera";
    make_path($camera_dir) unless -d $camera_dir;
    my $out = "$camera_dir/live.jpg";
    if (-s $out && time - (stat($out))[9] < 1) {
        return send_jpeg_file($client, $out);
    }
    my $r = capture_camera_to($out);
    if (!$r->{ok} && !-s $out) {
        return send_json($client, 500, $r);
    }
    return send_jpeg_file($client, $out);
}

sub send_mjpeg_stream {
    my ($client, $q) = @_;
    my $width  = int($q->{width}  || $ENV{CAMERA_STREAM_WIDTH}  || 640);
    my $height = int($q->{height} || $ENV{CAMERA_STREAM_HEIGHT} || 480);
    my $fps    = int($q->{fps}    || $ENV{CAMERA_STREAM_FPS}    || 30);
    my $quality = int($q->{quality} || $ENV{CAMERA_STREAM_QUALITY} || 75);
    $width = 640 if $width <= 0;
    $height = 480 if $height <= 0;
    $fps = 30 if $fps <= 0 || $fps > 30;
    $quality = 75 if $quality <= 0 || $quality > 100;

    my $started = start_camera_stream_producer($width, $height, $fps, $quality);
    if (!$started->{ok}) {
        return send_json($client, 500, $started);
    }

    my $boundary = 'zykhframe';
    print {$client} "HTTP/1.1 200 OK\r\n";
    print {$client} "Content-Type: multipart/x-mixed-replace; boundary=$boundary\r\n";
    print {$client} "Cache-Control: no-store, no-cache, must-revalidate\r\n";
    print {$client} "Pragma: no-cache\r\n";
    print {$client} "Connection: close\r\n\r\n";
    binmode $client, ':raw';

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
}

sub start_camera_stream_producer {
    my ($width, $height, $fps, $quality) = @_;
    stop_camera_preview(1);
    my $pidfile = "$DATA_DIR/camera-stream.pid";
    my $existing = -f $pidfile ? read_file_trim($pidfile) : '';
    if ($existing =~ /^\d+$/ && kill(0, $existing)) {
        return { ok => JSON::PP::true, pid => $existing, reused => JSON::PP::true };
    }

    my $stream_dir = "$DATA_DIR/stream";
    make_path($stream_dir) unless -d $stream_dir;
    unlink glob("$stream_dir/frame-*.jpg");
    my $device = detect_camera_device();
    my $logfile = "$DATA_DIR/camera-stream.log";
    my $cmd = $ENV{CAMERA_STREAM_CMD} ||
        'gst-launch-1.0 -q v4l2src device=' . shell_quote($device) . ' ' .
        '! video/x-raw,format=NV12,width=' . $width . ',height=' . $height . ',framerate=' . $fps . '/1 ' .
        '! videoconvert ! jpegenc quality=' . $quality . ' ' .
        '! multifilesink location=' . shell_quote("$stream_dir/frame-%05d.jpg") . ' max-files=3 sync=false';
    my $shell = "$cmd > " . shell_quote($logfile) . " 2>&1 & echo \$! > " . shell_quote($pidfile);
    my $rc = system('sh', '-c', $shell);
    my $pid = -s $pidfile ? read_file_trim($pidfile) : '';

    for (1..20) {
        return { ok => JSON::PP::true, pid => $pid, device => $device, command => $cmd } if latest_stream_frame();
        select(undef, undef, undef, 0.1);
    }
    my $log = read_text_file($logfile);
    stop_camera_stream_producer();
    return { ok => JSON::PP::false, error => '摄像头视频流没有生成画面', detail => substr($log, 0, 300), command => $cmd, rc => $rc };
}

sub stop_camera_stream_producer {
    my $pidfile = "$DATA_DIR/camera-stream.pid";
    my $pid = -f $pidfile ? read_file_trim($pidfile) : '';
    if ($pid =~ /^\d+$/) {
        system('kill', $pid);
        unlink $pidfile;
    }
    system('sh', '-c', "pkill -f 'multifilesink location=.*/frame-%05d.jpg' 2>/dev/null");
    return { ok => JSON::PP::true, detail => '摄像头浏览器视频流已停止' };
}

sub latest_stream_frame {
    my $stream_dir = "$DATA_DIR/stream";
    my @files = grep { -s $_ } glob("$stream_dir/frame-*.jpg");
    return '' unless @files;
    @files = sort { (stat($b))[9] <=> (stat($a))[9] || $b cmp $a } @files;
    return $files[0];
}

sub send_jpeg_file {
    my ($client, $path) = @_;
    return send_json($client, 404, { ok => JSON::PP::false, error => '没有可用摄像头图像' }) unless -s $path;
    open my $fh, '<:raw', $path or return send_json($client, 500, { ok => JSON::PP::false, error => "读取摄像头帧失败: $!" });
    local $/;
    my $body = <$fh>;
    close $fh;
    return send_text($client, 200, 'image/jpeg', $body);
}

sub capture_camera_to {
    my ($out) = @_;
    stop_camera_stream_producer();
    stop_camera_preview(1);
    select(undef, undef, undef, 0.5);
    unlink $out if -e $out;
    my $cmd = $ENV{CAMERA_CAPTURE_CMD};
    if ($cmd && $cmd =~ /\{out\}/) {
        $cmd =~ s/\{out\}/shell_quote($out)/eg;
    } elsif ($cmd) {
        $cmd .= ' ' . shell_quote($out);
    } else {
        my $device = detect_camera_device();
        $cmd = 'gst-launch-1.0 -q v4l2src device=' . shell_quote($device) . ' num-buffers=5 ' .
               '! video/x-raw,format=NV12,width=640,height=480,framerate=30/1 ' .
               '! videoconvert ! jpegenc ! filesink location=' . shell_quote($out);
    }

    my $logfile = "$DATA_DIR/camera-capture.log";
    my $run_cmd = $cmd . ' >' . shell_quote($logfile) . ' 2>&1';
    my $rc;
    {
        local $SIG{CHLD} = 'DEFAULT';
        $rc = system('timeout', '8', 'sh', '-c', $run_cmd);
    }
    my $exit = $rc == -1 ? -1 : ($rc >> 8);
    my $signal = $rc == -1 ? 0 : ($rc & 127);
    return { ok => JSON::PP::true, command => $cmd, exit_code => $exit, signal => $signal } if -s $out;
    my $log = read_text_file($logfile);
    $log = substr($log, -1200) if defined $log && length($log) > 1200;
    return { ok => JSON::PP::false, error => '摄像头抓帧失败', command => $cmd, exit_code => $exit, signal => $signal, log => $log || '' };
}

sub start_camera_preview {
    my ($p) = @_;
    my $output = $p->{output} || $ENV{CAMERA_OUTPUT} || detect_display_output();
    my $conf = "/tmp/.weston_drm.conf";
    if (open my $fh, '>', $conf) {
        print {$fh} "output:$output:primary\n";
        close $fh;
    } else {
        return { ok => JSON::PP::false, error => "无法写入 $conf: $!" };
    }

    stop_camera_preview(1);

    my $pidfile = "$DATA_DIR/camera-preview.pid";
    my $logfile = "$DATA_DIR/camera-preview.log";
    my $device = detect_camera_device();
    my $cmd = $ENV{CAMERA_PREVIEW_CMD} ||
        'gst-launch-1.0 -v v4l2src device=' . shell_quote($device) . ' ' .
        '! video/x-raw,format=NV12,width=640,height=480,framerate=30/1 ' .
        '! videoconvert ! waylandsink sync=false';

    my $shell = "export XDG_RUNTIME_DIR=/run; export WAYLAND_DISPLAY=wayland-0; " .
                "$cmd > " . shell_quote($logfile) . " 2>&1 & echo \$! > " . shell_quote($pidfile);
    my $rc = system('sh', '-c', $shell);
    if ($rc != 0 || !-s $pidfile) {
        return { ok => JSON::PP::false, error => '摄像头预览启动失败', command => $cmd, output => $output };
    }
    my $pid = read_file_trim($pidfile);
    add_record('摄像头预览', 0, 'camera_preview', 'success', "输出到 $output，PID $pid");
    return {
        ok => JSON::PP::true,
        detail => "摄像头预览已打开，输出到 $output",
        output => $output,
        device => $device,
        pid => $pid,
        command => $cmd,
    };
}

sub ai_chat {
    my ($p) = @_;
    my $message = trim($p->{message} || '');
    return { ok => JSON::PP::false, error => '请输入问诊内容' } if $message eq '';

    my $api_key = ai_api_key();
    if ($api_key eq '') {
        return {
            ok => JSON::PP::true,
            reply => 'AI 问诊接口还没有配置 API Key。请设置 AI_API_KEY，或把密钥保存到 /userdata/zykh_app/data/ai-api-key.txt。当前可以先测试语音输入和播报流程。',
            source => 'local-placeholder',
        };
    }

    my $base = $ENV{AI_API_BASE} || 'https://api.deepseek.com/chat/completions';
    my $model = $ENV{AI_MODEL} || 'deepseek-v4-flash';
    my $req_file = "$DATA_DIR/ai-request.json";
    my $res_file = "$DATA_DIR/ai-response.json";
    my $payload = build_ai_payload($message, JSON::PP::false);

    my $json = encode_json($payload);
    write_raw_file($req_file, $json);
    my $http = https_post_json_via_openssl($base, $api_key, $json, $res_file);
    if (!$http->{ok}) {
        return {
            ok => JSON::PP::false,
            error => 'AI 接口请求失败，请检查网络、API Key、API 地址和模型名',
            detail => $http->{error} || '',
            status => $http->{status} || 0,
            raw => substr($http->{body} || $http->{raw} || '', 0, 500),
        };
    }
    my $raw = $http->{body};
    my $obj = eval { decode_json($raw) };
    if (!$obj) {
        return { ok => JSON::PP::false, error => 'AI 响应不是有效 JSON', raw => substr($raw, 0, 300) };
    }
    if ($obj->{error}) {
        return { ok => JSON::PP::false, error => $obj->{error}{message} || 'AI 接口返回错误', source => 'ai', status => $http->{status} || 0 };
    }
    my $reply = $obj->{choices}[0]{message}{content} || 'AI 暂无回复';
    return { ok => JSON::PP::true, reply => $reply, source => 'ai', model => $model };
}

sub send_ai_chat_stream {
    my ($client, $p) = @_;
    my $message = trim($p->{message} || '');
    if ($message eq '') {
        return send_json($client, 200, { ok => JSON::PP::false, error => '请输入问诊内容' });
    }

    my $api_key = ai_api_key();
    if ($api_key eq '') {
        sse_headers($client);
        send_sse($client, 'error', { error => 'AI 问诊接口还没有配置 API Key' });
        send_sse($client, 'done', { ok => JSON::PP::false });
        return;
    }

    sse_headers($client);
    my $base = $ENV{AI_API_BASE} || 'https://api.deepseek.com/chat/completions';
    my $model = $ENV{AI_MODEL} || 'deepseek-v4-flash';
    my $payload = build_ai_payload($message, JSON::PP::true);
    send_sse($client, 'meta', { model => $model, source => 'ai', context => ai_context_summary() });
    return stream_ai_via_openssl($client, $base, $api_key, encode_json($payload));
}

sub ai_api_key {
    my $api_key = trim($ENV{AI_API_KEY} || '');
    if ($api_key eq '') {
        my $key_file = $ENV{AI_API_KEY_FILE} || "$DATA_DIR/ai-api-key.txt";
        $api_key = read_file_trim($key_file) if -s $key_file;
    }
    return $api_key;
}

sub build_ai_payload {
    my ($message, $stream) = @_;
    my $model = $ENV{AI_MODEL} || 'deepseek-v4-flash';
    return {
        model => $model,
        messages => [
            {
                role => 'system',
                content => ai_system_prompt(),
            },
            {
                role => 'user',
                content => "用户本次问题：$message\n\n请结合上面的老人档案、最近体征和本机药柜库存回答。若信息不足，先说明需要补充哪些信息。"
            },
        ],
        thinking => { type => 'disabled' },
        temperature => 0.25,
        stream => $stream ? JSON::PP::true : JSON::PP::false,
    };
}

sub ai_system_prompt {
    return join("\n", (
        '你是“智药康护”家庭智慧康护终端中的 AI 问诊助手，使用中文回答。',
        '你的工作是：解释常见健康知识、结合老人档案做风险提醒、提醒按医嘱用药、提示何时需要线下就医。',
        '严格限制：你不是医生，不能替代诊断，不能开处方，不能建议用户自行新增/停用处方药，不能自行调整剂量。',
        '药柜库存只表示家中现有药品，不能因为药柜里有某种药就建议直接服用；只能说“如果这是医生已开具/正在服用的药，请按医嘱”。',
        '遇到胸痛、呼吸困难、意识障碍、严重过敏、单侧肢体无力、血压持续超过 180/110 mmHg 等高危情况，必须建议立即急救或就医。',
        '回答格式要适合老人和家属听：先给一句结论，再列 3 到 5 条具体做法，最后说明何时必须就医。',
        '',
        '以下是本机可用上下文：',
        ai_context_text(),
    ));
}

sub ai_context_summary {
    my $profile = get_profile();
    my $vitals = list_vitals();
    return {
        patient => $profile->{name} || '未填写',
        latest_vitals_time => @$vitals ? $vitals->[0]{created_at} : '',
        medicine_count => scalar @{list_medicines()},
    };
}

sub ai_context_text {
    my $profile = get_profile();
    my $vitals = list_vitals();
    my $medicines = list_medicines();
    my $memories = list_memories();
    my @lines;
    push @lines, '【老人基本信息】';
    push @lines, '姓名：' . ($profile->{name} || '未填写');
    push @lines, '性别：' . ($profile->{gender} || '未填写') . '；年龄：' . (($profile->{age} || 0) ? $profile->{age} . '岁' : '未填写');
    push @lines, '身高：' . ($profile->{height} || '未填写') . '；体重：' . ($profile->{weight} || '未填写');
    push @lines, '慢病/病史：' . ($profile->{conditions} || '未填写');
    push @lines, '过敏史：' . ($profile->{allergies} || '未填写');
    push @lines, '备注：' . ($profile->{notes} || '无');
    push @lines, '';
    push @lines, '【最近体征】';
    if (@$vitals) {
        for my $v (@{$vitals}[0 .. (@$vitals > 4 ? 4 : @$vitals - 1)]) {
            push @lines, join('；',
                $v->{created_at},
                '体温 ' . ($v->{temperature} || '--') . '℃',
                '心率 ' . ($v->{heart_rate} || '--') . '次/分',
                '血氧 ' . ($v->{spo2} || '--') . '%',
                '血压 ' . (($v->{systolic} || '--') . '/' . ($v->{diastolic} || '--')) . ' mmHg',
                '来源 ' . ($v->{source} || '--')
            );
        }
    } else {
        push @lines, '暂无记录';
    }
    push @lines, '';
    push @lines, '【病例/护理记忆】';
    if (@$memories) {
        for my $memory (@{$memories}[0 .. (@$memories > 7 ? 7 : @$memories - 1)]) {
            push @lines, join('；',
                ($memory->{happened_at} || $memory->{created_at} || '时间未填'),
                $memory->{type} || 'case',
                $memory->{title} || '',
                $memory->{content} || ''
            );
        }
    } else {
        push @lines, '暂无病例或护理记录';
    }
    push @lines, '';
    push @lines, '【药柜库存】';
    if (@$medicines) {
        for my $m (@$medicines) {
            push @lines, $m->{slot} . '号仓：' . $m->{name} . '；规格/剂量：' . ($m->{dosage} || '--') . '；余量：' . ($m->{stock} || 0) . '；有效期：' . ($m->{expire_date} || '--');
        }
    } else {
        push @lines, '暂无药品';
    }
    return join("\n", @lines);
}

sub https_post_json_via_openssl {
    my ($url, $api_key, $json, $res_file) = @_;
    return { ok => JSON::PP::false, error => '仅支持 https:// API 地址' } unless $url =~ m{^https://([^/:]+)(?::(\d+))?(/.*)$};
    my ($host, $port, $path) = ($1, $2 || 443, $3);
    my $req_file = "$DATA_DIR/ai-http-request.txt";
    my $raw_file = "$DATA_DIR/ai-http-response.raw";
    my $err_file = "$DATA_DIR/ai-http-error.log";
    my $body_len = length($json);
    my $request =
        "POST $path HTTP/1.1\r\n" .
        "Host: $host\r\n" .
        "User-Agent: zykh-app/1.0\r\n" .
        "Accept: application/json\r\n" .
        "Content-Type: application/json\r\n" .
        "Authorization: Bearer $api_key\r\n" .
        "Content-Length: $body_len\r\n" .
        "Connection: close\r\n\r\n" .
        $json;
    write_raw_file($req_file, $request);
    chmod 0600, $req_file;

    my $cmd = 'openssl s_client -connect ' . shell_quote("$host:$port") .
              ' -servername ' . shell_quote($host) .
              ' -quiet <' . shell_quote($req_file) .
              ' >' . shell_quote($raw_file) .
              ' 2>' . shell_quote($err_file);
    my $rc;
    {
        local $SIG{CHLD} = 'DEFAULT';
        $rc = system('timeout', '45', 'sh', '-c', $cmd);
    }
    unlink $req_file;
    my $raw = read_raw_file($raw_file);
    my $err = read_text_file($err_file);
    my ($status, $body) = parse_http_response($raw);
    write_raw_file($res_file, $body) if defined $body && length($body);
    return { ok => JSON::PP::true, status => $status, body => $body, raw => $raw } if $status >= 200 && $status < 300 && defined $body && length($body);
    my $exit = $rc == -1 ? -1 : ($rc >> 8);
    return { ok => JSON::PP::false, status => $status || 0, body => $body || '', raw => $raw || '', error => "openssl exit=$exit " . substr($err || '', 0, 300) };
}

sub stream_ai_via_openssl {
    my ($client, $url, $api_key, $json) = @_;
    if ($url !~ m{^https://([^/:]+)(?::(\d+))?(/.*)$}) {
        send_sse($client, 'error', { error => '仅支持 https:// API 地址' });
        send_sse($client, 'done', { ok => JSON::PP::false });
        return;
    }
    my ($host, $port, $path) = ($1, $2 || 443, $3);
    my $req_file = "$DATA_DIR/ai-stream-request.txt";
    my $err_file = "$DATA_DIR/ai-stream-error.log";
    my $body_len = length($json);
    my $request =
        "POST $path HTTP/1.1\r\n" .
        "Host: $host\r\n" .
        "User-Agent: zykh-app/1.0\r\n" .
        "Accept: text/event-stream\r\n" .
        "Content-Type: application/json\r\n" .
        "Authorization: Bearer $api_key\r\n" .
        "Content-Length: $body_len\r\n" .
        "Connection: close\r\n\r\n" .
        $json;
    write_raw_file($req_file, $request);
    chmod 0600, $req_file;

    my $cmd = 'openssl s_client -connect ' . shell_quote("$host:$port") .
              ' -servername ' . shell_quote($host) .
              ' -quiet <' . shell_quote($req_file) .
              ' 2>' . shell_quote($err_file);
    my $pipe;
    {
        local $SIG{CHLD} = 'DEFAULT';
        open $pipe, '-|', 'sh', '-c', $cmd;
    }
    if (!$pipe) {
        unlink $req_file;
        send_sse($client, 'error', { error => '无法启动 openssl 流式请求' });
        send_sse($client, 'done', { ok => JSON::PP::false });
        return;
    }
    binmode $pipe, ':raw';

    my $buffer = '';
    my $headers = '';
    my $header_done = 0;
    my $chunk_buffer = '';
    my $sse_buffer = '';
    my $reply = '';
    my $status = 0;
    my $done = 0;
    my $tmp;

    while (!$done && read($pipe, $tmp, 2048)) {
        $buffer .= $tmp;
        if (!$header_done) {
            if ($buffer =~ s/\A(.*?)\r?\n\r?\n//s) {
                $headers = $1;
                ($status) = $headers =~ m{^HTTP/\S+\s+(\d+)}m;
                if (!$status || $status < 200 || $status >= 300) {
                    send_sse($client, 'error', { error => 'AI 接口返回 HTTP ' . ($status || 0), raw => substr($buffer, 0, 300) });
                    $done = 1;
                    last;
                }
                $header_done = 1;
                $chunk_buffer .= $buffer;
                $buffer = '';
            } else {
                next;
            }
        } else {
            $chunk_buffer .= $buffer;
            $buffer = '';
        }

        while ($chunk_buffer =~ /\A([0-9a-fA-F]+)[^\r\n]*\r?\n/s) {
            my $prefix = $&;
            my $len = hex($1);
            my $need = length($prefix) + $len + 1;
            last if length($chunk_buffer) < $need;
            substr($chunk_buffer, 0, length($prefix), '');
            last if $len == 0;
            my $piece = substr($chunk_buffer, 0, $len, '');
            $chunk_buffer =~ s/\A\r?\n//s;
            $sse_buffer .= $piece;

            while ($sse_buffer =~ s/\A(.*?\r?\n\r?\n)//s) {
                my $event = $1;
                for my $line (split /\r?\n/, $event) {
                    next unless $line =~ /^data:\s*(.*)$/;
                    my $data = $1;
                    if ($data eq '[DONE]') {
                        send_sse($client, 'done', { ok => JSON::PP::true, reply => $reply });
                        $done = 1;
                        last;
                    }
                    my $obj = eval { decode_json($data) };
                    next unless $obj;
                    my $delta = $obj->{choices}[0]{delta}{content} || '';
                    if ($delta ne '') {
                        $reply .= $delta;
                        send_sse($client, 'delta', { delta => $delta });
                    }
                }
                last if $done;
            }
        }
    }

    close $pipe;
    unlink $req_file;
    if (!$done) {
        my $err = read_text_file($err_file);
        if ($reply ne '') {
            send_sse($client, 'done', { ok => JSON::PP::true, reply => $reply });
        } else {
            send_sse($client, 'error', { error => 'AI 流式响应中断', detail => substr($err || '', 0, 240) });
            send_sse($client, 'done', { ok => JSON::PP::false });
        }
    }
}

sub sse_headers {
    my ($client) = @_;
    print {$client} "HTTP/1.1 200 OK\r\n";
    print {$client} "Content-Type: text/event-stream; charset=utf-8\r\n";
    print {$client} "Cache-Control: no-cache\r\n";
    print {$client} "Access-Control-Allow-Origin: *\r\n";
    print {$client} "Connection: close\r\n\r\n";
}

sub send_sse {
    my ($client, $event, $obj) = @_;
    print {$client} "event: $event\n";
    print {$client} 'data: ' . encode_json($obj || {}) . "\n\n";
}

sub parse_http_response {
    my ($raw) = @_;
    return (0, '') unless defined $raw && length $raw;
    my $head = '';
    my $body = $raw;
    if ($raw =~ /\r\n\r\n/s) {
        ($head, $body) = split /\r\n\r\n/, $raw, 2;
    } elsif ($raw =~ /\n\n/s) {
        ($head, $body) = split /\n\n/, $raw, 2;
    }
    my ($status) = $head =~ m{^HTTP/\S+\s+(\d+)}m;
    if ($head =~ /^Transfer-Encoding:\s*chunked\s*$/mi) {
        $body = decode_chunked_body($body);
    }
    return ($status || 0, $body || '');
}

sub decode_chunked_body {
    my ($body) = @_;
    my $out = '';
    while (defined $body && $body =~ s/\A([0-9a-fA-F]+)[^\r\n]*\r?\n//s) {
        my $len = hex($1);
        last if $len == 0;
        last if length($body) < $len;
        $out .= substr($body, 0, $len, '');
        $body =~ s/\A\r?\n//s;
    }
    return $out;
}

sub write_raw_file {
    my ($file, $body) = @_;
    open my $fh, '>:raw', $file or return 0;
    print {$fh} $body;
    close $fh;
    return 1;
}

sub read_raw_file {
    my ($file) = @_;
    return '' unless -f $file;
    open my $fh, '<:raw', $file or return '';
    local $/;
    my $body = <$fh>;
    close $fh;
    return defined $body ? $body : '';
}

sub stop_camera_preview {
    my ($quiet) = @_;
    my $pidfile = "$DATA_DIR/camera-preview.pid";
    my $pid = -f $pidfile ? read_file_trim($pidfile) : '';
    if ($pid =~ /^\d+$/) {
        system('kill', $pid);
        unlink $pidfile;
        add_record('摄像头预览', 0, 'camera_preview_stop', 'success', "已关闭 PID $pid") unless $quiet;
        return { ok => JSON::PP::true, detail => '摄像头预览已关闭', pid => $pid };
    }
    system('sh', '-c', "pkill -f 'waylandsink sync=false' 2>/dev/null");
    return { ok => JSON::PP::true, detail => '当前没有运行中的摄像头预览' };
}

sub detect_display_output {
    return 'HDMI-A-1' if drm_status('HDMI-A-1') eq 'connected';
    return 'LVDS-1' if drm_status('LVDS-1') eq 'connected';
    return 'DSI-1' if drm_status('DSI-1') eq 'connected';
    return 'HDMI-A-1';
}

sub detect_camera_device {
    return $ENV{CAMERA_DEVICE} if $ENV{CAMERA_DEVICE};
    return '/dev/video5' if -e '/dev/video5';
    my $cache = "$DATA_DIR/camera-device.txt";
    my $cached = read_file_trim($cache);
    return $cached if $cached && -e $cached;
    for my $dev ('/dev/video5', '/dev/video-camera0', '/dev/video14') {
        next unless -e $dev;
        my $cmd = 'gst-launch-1.0 -q v4l2src device=' . shell_quote($dev) .
                  ' num-buffers=2 ! video/x-raw,format=NV12,width=640,height=480,framerate=30/1 ' .
                  '! fakesink sync=false';
        my $rc = system('timeout', '2', 'sh', '-c', $cmd);
        if ($rc == 0) {
            write_text_file($cache, $dev);
            return $dev;
        }
    }
    return '/dev/video-camera0';
}

sub drm_status {
    my ($name) = @_;
    my $path = "/sys/class/drm/card0-$name/status";
    return '' unless -f $path;
    return read_file_trim($path);
}

sub read_file_trim {
    my ($path) = @_;
    open my $fh, '<', $path or return '';
    my $v = <$fh> // '';
    close $fh;
    chomp $v;
    $v =~ s/^\s+|\s+$//g;
    return $v;
}

sub write_text_file {
    my ($path, $text) = @_;
    open my $fh, '>:encoding(UTF-8)', $path or die "write $path failed: $!";
    print {$fh} $text;
    close $fh;
}

sub read_text_file {
    my ($path) = @_;
    open my $fh, '<:encoding(UTF-8)', $path or return '';
    local $/;
    my $text = <$fh>;
    close $fh;
    return $text;
}

sub shell_quote {
    my ($s) = @_;
    $s =~ s/'/'"'"'/g;
    return "'$s'";
}

sub serve_static {
    my ($client, $file) = @_;
    if (!-f $file) {
        return send_text($client, 404, 'text/plain; charset=utf-8', "404 Not Found\n");
    }
    open my $fh, '<:raw', $file or return send_text($client, 500, 'text/plain', "open failed\n");
    local $/;
    my $body = <$fh>;
    close $fh;
    send_text($client, 200, mime_type($file), $body);
}

sub mime_type {
    my ($file) = @_;
    return 'text/html; charset=utf-8' if $file =~ /\.html$/;
    return 'text/css; charset=utf-8'  if $file =~ /\.css$/;
    return 'application/javascript; charset=utf-8' if $file =~ /\.js$/;
    return 'image/png' if $file =~ /\.png$/;
    return 'image/jpeg' if $file =~ /\.jpe?g$/;
    return 'image/svg+xml' if $file =~ /\.svg$/;
    return 'application/octet-stream';
}

sub send_json {
    my ($client, $status, $obj) = @_;
    send_text($client, $status, 'application/json; charset=utf-8', encode_json($obj));
}

sub send_text {
    my ($client, $status, $type, $body) = @_;
    my %status_text = (200 => 'OK', 404 => 'Not Found', 500 => 'Internal Server Error');
    my $reason = $status_text{$status} || 'OK';
    print {$client} "HTTP/1.1 $status $reason\r\n";
    print {$client} "Content-Type: $type\r\n";
    print {$client} "Access-Control-Allow-Origin: *\r\n";
    print {$client} "Connection: close\r\n";
    print {$client} "Content-Length: " . length($body) . "\r\n\r\n";
    print {$client} $body;
}

sub trim {
    my ($s) = @_;
    $s = '' unless defined $s;
    $s =~ s/^\s+|\s+$//g;
    return $s;
}

sub basename {
    my ($path) = @_;
    $path =~ s#^.*/##;
    return $path;
}
