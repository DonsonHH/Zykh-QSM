#!/usr/bin/env perl
use strict;
use warnings;
use utf8;
use IO::Socket::INET;
use JSON::PP qw(encode_json decode_json);
use MIME::Base64 qw(encode_base64 decode_base64);
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

    return unless ($ENV{ZYKH_SEED_DEMO_MEDICINES} || '') eq '1';
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

sub url_encode {
    my ($s) = @_;
    $s = '' unless defined $s;
    my $bytes = Encode::encode('UTF-8', "$s");
    $bytes =~ s/([^A-Za-z0-9\-_.~])/sprintf("%%%02X", ord($1))/eg;
    return $bytes;
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
    if ($method eq 'GET' && $path eq '/api/network/status') {
        return send_json($client, 200, qsm_network_status());
    }
    if ($method eq 'POST' && $path eq '/api/network/start_4g') {
        return send_json($client, 200, start_qsm_4g_network());
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
    if ($method eq 'POST' && $path eq '/api/medicine/visual_recognize') {
        return send_json($client, 200, visual_recognize_medicine($req->{params}));
    }
    if ($method eq 'POST' && $path eq '/api/medicine/expiry_ocr') {
        return send_json($client, 200, recognize_expiry_date($req->{params}));
    }
    if ($method eq 'POST' && $path eq '/api/medicine/expiry_vision') {
        return send_json($client, 200, recognize_expiry_date($req->{params}));
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
    if ($method eq 'POST' && $path eq '/api/vitals/temp/read') {
        return send_json($client, 200, read_temperature());
    }
    if ($method eq 'POST' && $path eq '/api/vitals/read_all') {
        return send_json($client, 200, read_all_vitals());
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
    if ($method eq 'POST' && $path eq '/api/audio/asr') {
        return send_json($client, 200, audio_asr($req->{params}));
    }
    if ($method eq 'POST' && $path eq '/api/audio/speak') {
        return send_json($client, 200, speak_text($req->{params}));
    }
    if ($method eq 'POST' && $path eq '/api/audio/beep') {
        return send_json($client, 200, play_beep($req->{params}));
    }
    if ($method eq 'POST' && $path eq '/api/audio/play') {
        return send_json($client, 200, play_uploaded_audio($req->{params}));
    }
    if ($method eq 'POST' && $path eq '/api/audio/stream/start') {
        return send_json($client, 200, start_audio_pcm_stream($req->{params}));
    }
    if ($method eq 'POST' && $path eq '/api/audio/stream/stop') {
        return send_json($client, 200, stop_audio_pcm_stream());
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
        network => qsm_network_status(),
    };
}

sub qsm_network_status {
    my $interface = $ENV{SIM_NET_IFACE} || 'usb0';
    my $lsusb = trim(`lsusb 2>/dev/null | grep -i -E '2c7c:6005|quectel|ec200' | head -1`);
    my @tty = map { basename($_) } glob('/dev/ttyUSB*');
    my $at = read_ec200a_at_status();
    my $ifconfig = `ifconfig $interface 2>/dev/null`;
    my ($ip) = $ifconfig =~ /inet (?:addr:)?(\d+\.\d+\.\d+\.\d+)/;
    my $ip_is_4g = ($ip && $ip =~ /^10\./) ? 1 : 0;
    my $route = `route -n 2>/dev/null`;
    my $default_iface = '';
    for my $line (split /\r?\n/, $route) {
        my @parts = split /\s+/, trim($line);
        next unless @parts >= 8 && $parts[0] eq '0.0.0.0';
        $default_iface = $parts[-1];
        last;
    }
    my $route_ok = $default_iface eq $interface ? 1 : 0;
    my $ping_ok = ($ip_is_4g && $route_ok) ? ping_once($ENV{SIM_PING_IP} || '223.5.5.5') : 0;
    my $sim_present = ($lsusb ne '' || @tty || $ifconfig ne '' || $at->{at_ok}) ? JSON::PP::true : JSON::PP::false;
    my $connected_bool = ($ip_is_4g && $route_ok && ($ping_ok || $at->{registered})) ? 1 : 0;
    my $connected = $connected_bool ? JSON::PP::true : JSON::PP::false;
    my $signal = $connected_bool ? 'good' : ($sim_present ? 'weak' : 'none');
    my $status = $connected_bool ? 'good' : ($sim_present ? 'weak' : 'unavailable');
    my $detail;
    if ($connected_bool) {
        $detail = 'SIM 数据网络已连通';
    } elsif ($at->{sim_ready} && $at->{registered}) {
        $detail = 'SIM 已就绪并注册网络，但数据出口未连通';
    } elsif ($at->{sim_ready}) {
        $detail = 'SIM 已就绪，尚未确认网络注册';
    } elsif ($sim_present) {
        $detail = '已检测到 SIM 通信模块，但 SIM 或数据网络未就绪';
    } else {
        $detail = '未检测到 SIM 通信模块';
    }
    return {
        ok => JSON::PP::true,
        mode => 'sim',
        interface => $interface,
        sim_present => $sim_present,
        connected => $connected,
        signal => $signal,
        status => $status,
        ip => $ip || '',
        ip_is_4g => $ip_is_4g ? JSON::PP::true : JSON::PP::false,
        route_ok => $route_ok ? JSON::PP::true : JSON::PP::false,
        ping_ok => $ping_ok ? JSON::PP::true : JSON::PP::false,
        default_interface => $default_iface,
        tty_usb => \@tty,
        modem => $lsusb,
        at => $at,
        detail => $detail,
    };
}

sub start_qsm_4g_network {
    my $script = $ENV{QSM_4G_SCRIPT} || "$HOME_DIR/scripts/start_4g.sh";
    return {
        ok => JSON::PP::false,
        error => '4G 启动脚本不存在',
        script => $script,
        network => qsm_network_status(),
    } unless -f $script;

    my $log = "$DATA_DIR/start-4g.log";
    my $cmd = 'sh ' . shell_quote($script) . ' >' . shell_quote($log) . ' 2>&1';
    my $rc;
    {
        local $SIG{CHLD} = 'DEFAULT';
        $rc = system('timeout', int($ENV{QSM_4G_TIMEOUT} || 75), 'sh', '-c', $cmd);
    }
    my $exit = $rc == -1 ? -1 : ($rc >> 8);
    my $raw = redact_modem_identity(substr(read_text_file($log) || '', -1500));
    return {
        ok => $exit == 0 ? JSON::PP::true : JSON::PP::false,
        script => $script,
        exit_code => $exit,
        detail => $raw,
        network => qsm_network_status(),
    };
}

sub read_ec200a_at_status {
    my $port = $ENV{EC200A_AT_PORT} || '/dev/ttyUSB2';
    return {
        at_ok => JSON::PP::false,
        at_port => $port,
        sim_ready => JSON::PP::false,
        registered => JSON::PP::false,
        error => 'AT 口不存在',
    } unless $port && -e $port;

    my $out = '/tmp/zykh_ec200a_at_status.txt';
    my $delay = $ENV{EC200A_AT_DELAY} || '0.18';
    $delay = '0.18' unless $delay =~ /^\d+(?:\.\d+)?$/;
    my $timeout = int($ENV{EC200A_AT_TIMEOUT} || 4);
    $timeout = 2 if $timeout < 2;
    $timeout = 8 if $timeout > 8;
    my @commands = (
        'AT',
        'AT+CPIN?',
        'AT+CSQ',
        'AT+CREG?',
        'AT+CGREG?',
        'AT+CEREG?',
        'AT+COPS?',
        'AT+QNWINFO',
    );
    my $send = '';
    for my $command (@commands) {
        $send .= 'printf ' . shell_quote("$command\r\n") . ' > "$PORT"; sleep ' . $delay . '; ';
    }
    my $shell = 'PORT=' . shell_quote($port) . '; OUT=' . shell_quote($out) . '; ' .
        'stty -F "$PORT" 115200 raw -echo 2>/dev/null; rm -f "$OUT"; ' .
        'timeout ' . int($timeout) . ' cat "$PORT" > "$OUT" 2>/dev/null & reader=$!; sleep 0.20; ' .
        $send .
        'sleep 0.20; kill "$reader" 2>/dev/null; wait "$reader" 2>/dev/null; cat "$OUT" 2>/dev/null';
    my $raw = `$shell`;
    $raw ||= '';
    my $clean = normalize_at_text($raw);
    my $at_ok = $clean =~ /\bOK\b/ ? 1 : 0;
    my ($cpin) = $clean =~ /\+CPIN:\s*([A-Z ]+)/i;
    my $sim_ready = defined $cpin && $cpin =~ /READY/i ? 1 : 0;
    my ($csq) = $clean =~ /\+CSQ:\s*(\d+),/i;
    my $csq_value = defined $csq ? int($csq) : 99;
    my $signal_dbm = $csq_value == 99 ? '' : (-113 + 2 * $csq_value);
    my $creg = parse_registration_state($clean, 'CREG');
    my $cgreg = parse_registration_state($clean, 'CGREG');
    my $cereg = parse_registration_state($clean, 'CEREG');
    my $registered = (($creg =~ /^[15]$/) || ($cgreg =~ /^[15]$/) || ($cereg =~ /^[15]$/)) ? 1 : 0;
    my @operator_values = $clean =~ /\+COPS:[^\n]*"([^"\n]+)"/ig;
    my $operator = @operator_values ? $operator_values[-1] : '';
    my @network_info_values = $clean =~ /\+QNWINFO:\s*([^\n]+)/ig;
    my $network_info = @network_info_values ? trim($network_info_values[-1]) : '';
    my ($iccid) = $clean =~ /\+QCCID:\s*(\d+)/i;
    my @number_lines = $clean =~ /^\s*(\d{14,20})\s*$/mg;
    my $imsi = '';
    for my $number (@number_lines) {
        next if defined $iccid && $number eq $iccid;
        if (length($number) >= 14 && length($number) <= 16) {
            $imsi = $number;
            last;
        }
    }

    return {
        at_ok => $at_ok ? JSON::PP::true : JSON::PP::false,
        at_port => $port,
        sim_ready => $sim_ready ? JSON::PP::true : JSON::PP::false,
        registered => $registered ? JSON::PP::true : JSON::PP::false,
        signal_csq => $csq_value,
        signal_dbm => $signal_dbm,
        creg => $creg,
        cgreg => $cgreg,
        cereg => $cereg,
        operator => $operator || '',
        network_info => $network_info || '',
        iccid_masked => mask_sensitive_number($iccid || ''),
        imsi_masked => mask_sensitive_number($imsi || ''),
        error => $at_ok ? '' : 'AT 指令未返回 OK',
    };
}

sub parse_registration_state {
    my ($raw, $name) = @_;
    for my $line (split /\n/, normalize_at_text($raw || '')) {
        next unless $line =~ /^\s*\+\Q$name\E:\s*(.*)$/i;
        my @numbers = $1 =~ /(\d+)/g;
        return '' unless @numbers;
        return defined $numbers[1] ? "$numbers[1]" : "$numbers[0]";
    }
    return '';
}

sub at_line_payload {
    my ($raw, $name) = @_;
    for my $line (split /\n/, normalize_at_text($raw || '')) {
        next unless $line =~ /^\s*\+\Q$name\E:\s*(.*)$/i;
        return trim($1 || '');
    }
    return '';
}

sub normalize_at_text {
    my ($text) = @_;
    $text = '' unless defined $text;
    $text =~ s/\r/\n/g;
    $text =~ s/[^\x09\x0A\x0D\x20-\x7E]//g;
    return $text;
}

sub mask_sensitive_number {
    my ($value) = @_;
    $value = trim($value || '');
    return '' if $value eq '';
    return $value if length($value) <= 8;
    return substr($value, 0, 4) . '****' . substr($value, -4);
}

sub redact_modem_identity {
    my ($text) = @_;
    $text = '' unless defined $text;
    $text =~ s/(\+QCCID:\s*)\d+/$1****/ig;
    $text =~ s/^\s*\d{14,20}\s*$/****/mg;
    return $text;
}

sub ping_once {
    my ($target) = @_;
    return 0 unless $target;
    $target =~ s/[^A-Za-z0-9\.\-]//g;
    my $rc;
    {
        local $SIG{CHLD} = 'DEFAULT';
        $rc = system('sh', '-c', 'timeout 4 ping -c 1 -W 2 ' . shell_quote($target) . ' >/dev/null 2>&1');
    }
    return $rc == 0 ? 1 : 0;
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
        my $remote = lookup_showapi_barcode($code);
        return $remote if $remote->{ok} && $remote->{found};
        my $detail = '本地药品目录未收录该条码。';
        $detail .= ' ShowAPI：' . ($remote->{detail} || $remote->{error}) if $remote->{tried};
        $detail .= ' 请人工核对后录入，后续可继续导入本地目录。';
        return {
            ok => JSON::PP::true,
            found => JSON::PP::false,
            code => $code,
            detail => $detail,
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
    my $m;
    if ($lookup->{found}) {
        $m = $lookup->{medicine};
    } else {
        my $code = normalize_code($p->{code} || $p->{trace_code} || $lookup->{code} || '');
        return $lookup if $code eq '';
        $m = {
            code => $code,
            name => trim($p->{name} || "待确认药品($code)"),
            dosage => trim($p->{dosage} || ''),
            manufacturer => '',
            batch_no => '',
            expire_date => '',
            trace_code => '',
            note => '条码未被本地目录/ShowAPI 收录，由用户确认后临时录入。',
        };
        upsert_catalog_medicine($m);
    }
    my $box_size = normalize_box_size($p->{box_size} || suggest_box_size($m));
    my $slot = int($p->{slot} || first_empty_slot($box_size));
    my $stock = int($p->{stock} || estimate_stock($m) || 1);
    $stock = 1 if $stock < 1;
    my $expire = trim($p->{expire_date} || $m->{expire_date} || '');
    $m->{expire_date} = $expire if $expire ne '';
    my @existing = sqlite_row('SELECT id FROM medicines WHERE slot=' . int($slot) . ' AND stock > 0 ORDER BY id LIMIT 1;');
    if (@existing && defined $existing[0]) {
        sqlite_exec('UPDATE medicines SET name=' . sql_quote($m->{name}) .
            ', dosage=' . sql_quote($m->{dosage}) .
            ', stock=' . int($stock) .
            ', expire_date=' . sql_quote($expire) .
            ', created_at=' . sql_quote(now_text()) .
            ' WHERE id=' . int($existing[0]) . ';');
    } else {
        sqlite_exec('INSERT INTO medicines(name,slot,dosage,stock,expire_date,created_at) VALUES (' .
            join(',', map { sql_quote($_) } ($m->{name}, $slot, $m->{dosage}, $stock, $expire, now_text())) . ');');
    }
    add_record($m->{name}, $slot, 'medicine_auto_add', 'success', '商品条码自动录入：' . ($m->{code} || $m->{trace_code} || ''));
    return { ok => JSON::PP::true, found => JSON::PP::true, medicine => $m, slot => $slot, stock => $stock, box_size => $box_size, slot_kind => slot_kind($slot), medicines => list_medicines() };
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
        $detail = '已从摄像头图像识别到商品条码，格式：' . ($decoded->{format} || 'unknown');
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
        $detail = $code ? '已从摄像头图像识别到商品条码' : '未从图像中识别到商品条码';
    }

    $code ||= '';
    if ($code eq '') {
        my $vision = qwen_vision_from_image(
            $image,
            '请识别图片中的商品条形码。只返回 JSON，不要解释。字段：code_candidates 数组、format、confidence、detail。如果看不清，code_candidates 返回空数组。',
            'barcode'
        );
        if ($vision->{ok}) {
            my $v = $vision->{data} || {};
            if (ref($v->{code_candidates}) eq 'ARRAY') {
                ($code) = grep { $_ ne '' } map { normalize_code($_) } @{$v->{code_candidates}};
            }
            $scanner = 'qwen3.6-flash-vision';
            $detail = $code
                ? '本地解码未命中，已通过 Qwen3.6 视觉理解识别到候选条码。'
                : '本地解码和视觉理解都未识别到清晰商品条码。';
        }
    }

    if ($code eq '') {
        return {
            ok => JSON::PP::false,
            code => '',
            scanner => $scanner || 'none',
            detail => $detail || $decoded->{error} || '未识别到商品条码，请调整距离、光线和对焦后重试。',
            image_url => $capture->{image_url},
        };
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

sub lookup_showapi_barcode {
    my ($code) = @_;
    $code = normalize_code($code);
    return { ok => JSON::PP::true, found => JSON::PP::false, tried => JSON::PP::false, detail => '不是 69 开头国内商品条形码，跳过 ShowAPI 查询。' }
        unless $code =~ /^69\d{11}$/;
    my $app_key = showapi_app_key();
    return { ok => JSON::PP::true, found => JSON::PP::false, tried => JSON::PP::false, detail => '未配置 ShowAPI appKey。' }
        if $app_key eq '';

    my $url = 'https://route.showapi.com/66-24?appKey=' . url_encode($app_key);
    my $body = 'code=' . url_encode($code);
    my $res_file = "$DATA_DIR/showapi-barcode-response.json";
    my $http = https_post_form_via_openssl($url, $body, $res_file);
    if (!$http->{ok}) {
        return { ok => JSON::PP::true, found => JSON::PP::false, tried => JSON::PP::true, detail => '请求失败：' . ($http->{error} || 'unknown') };
    }
    my $json_text = eval { decode('UTF-8', $http->{body} || '', 1) };
    $json_text = $http->{body} || '' if !defined $json_text;
    my $obj = eval { JSON::PP->new->utf8(0)->decode($json_text) };
    if (!$obj) {
        return { ok => JSON::PP::true, found => JSON::PP::false, tried => JSON::PP::true, detail => '返回不是有效 JSON。' };
    }
    my $body_obj = $obj->{showapi_res_body} || {};
    my $ret = defined $body_obj->{ret_code} ? $body_obj->{ret_code} + 0 : -1;
    my $name = trim($body_obj->{name} || '');
    if (($obj->{showapi_res_code} || 0) != 0 || $ret != 0 || $name eq '') {
        return {
            ok => JSON::PP::true,
            found => JSON::PP::false,
            tried => JSON::PP::true,
            detail => $body_obj->{remark} || $obj->{showapi_res_error} || 'ShowAPI 未查询到药品条码信息。',
        };
    }

    my $medicine = showapi_to_catalog($code, $body_obj);
    upsert_catalog_medicine($medicine);
    return {
        ok => JSON::PP::true,
        found => JSON::PP::true,
        source => 'showapi',
        medicine => $medicine,
        detail => '已通过 ShowAPI 查询商品条码，并写入本地药品目录缓存。',
    };
}

sub showapi_to_catalog {
    my ($code, $b) = @_;
    my $dosage = join('；', grep { defined && $_ ne '' } (
        trim($b->{spec} || ''),
        trim($b->{dosage} || ''),
    ));
    my $note = join("\n", grep { defined && $_ ne '' } (
        '来源：ShowAPI 药品条码查询',
        '类型：' . trim($b->{type} || ''),
        '批准文号：' . trim($b->{approval} || ''),
        '商品名/商标：' . trim($b->{trademark} || ''),
        '功能主治/适用范围：' . trim($b->{purpose} || ''),
        '主要成分：' . trim($b->{basis} || ''),
        '注意事项：' . trim($b->{consideration} || ''),
        '贮藏：' . trim($b->{storage} || ''),
        '图片：' . trim($b->{img} || ''),
    ));
    return {
        code => $code,
        name => trim($b->{name} || '未知药品'),
        dosage => $dosage,
        manufacturer => trim($b->{manuName} || ''),
        batch_no => '',
        expire_date => trim($b->{validity} || ''),
        trace_code => '',
        note => $note,
    };
}

sub upsert_catalog_medicine {
    my ($m) = @_;
    sqlite_exec('INSERT OR REPLACE INTO medicine_catalog(code,name,dosage,manufacturer,batch_no,expire_date,trace_code,note,created_at) VALUES (' .
        join(',', map { sql_quote($_) } (
            $m->{code}, $m->{name}, $m->{dosage}, $m->{manufacturer}, $m->{batch_no},
            $m->{expire_date}, $m->{trace_code}, $m->{note}, now_text()
        )) . ');');
}

sub showapi_app_key {
    my $key = trim($ENV{SHOWAPI_APP_KEY} || '');
    if ($key eq '') {
        my $file = $ENV{SHOWAPI_APP_KEY_FILE} || "$DATA_DIR/showapi-app-key.txt";
        $key = read_file_trim($file) if -s $file;
    }
    return $key;
}

sub visual_recognize_medicine {
    my ($p) = @_;
    my $capture = capture_camera();
    return $capture unless $capture->{ok};
    my $image = "$WEB_DIR/camera/latest.jpg";
    my $cmd = $ENV{RKNN_MEDICINE_CMD} || '';
    if ($cmd eq '') {
        my $vision = qwen_vision_from_image(
            $image,
            '你是智能药柜的药盒视觉识别模块。请从图片中识别药品商品条码候选、药品名称、厂家、规格、批准文号和可见有效期。只返回 JSON，字段：code_candidates 数组、medicine_name、manufacturer、spec、approval、expiry_date、confidence、need_user_confirm、detail。',
            'medicine'
        );
        if ($vision->{ok}) {
            my $d = $vision->{data} || {};
            return {
                ok => JSON::PP::true,
                found => ($d->{medicine_name} || (ref($d->{code_candidates}) eq 'ARRAY' && @{$d->{code_candidates}})) ? JSON::PP::true : JSON::PP::false,
                source => 'qwen3.6-flash',
                image_url => $capture->{image_url},
                result => $d,
                detail => $d->{detail} || '已调用 Qwen3.6 视觉理解，请在确认页核对后录入。',
            };
        }
        return {
            ok => JSON::PP::false,
            found => JSON::PP::false,
            source => 'qwen3.6-flash',
            image_url => $capture->{image_url},
            detail => 'Qwen3.6 视觉理解调用失败：' . ($vision->{error} || 'unknown'),
        };
    }
    $cmd =~ s/\{image\}/shell_quote($image)/eg;
    my $log = "$DATA_DIR/rknn-medicine.log";
    my $rc;
    {
        local $SIG{CHLD} = 'DEFAULT';
        $rc = system('timeout', '30', 'sh', '-c', $cmd . ' >' . shell_quote($log) . ' 2>&1');
    }
    my $raw = read_text_file($log);
    my $exit = $rc == -1 ? -1 : ($rc >> 8);
    my $obj = eval { decode_json($raw || '') };
    if ($obj && $obj->{ok}) {
        $obj->{image_url} ||= $capture->{image_url};
        $obj->{source} ||= 'rknn';
        return $obj;
    }
    return {
        ok => $exit == 0 ? JSON::PP::true : JSON::PP::false,
        found => JSON::PP::false,
        source => 'rknn',
        image_url => $capture->{image_url},
        detail => $exit == 0 ? 'RKNN 命令已执行，但未返回可解析药品结果。' : 'RKNN 命令执行失败。',
        raw => substr($raw || '', 0, 600),
        exit_code => $exit,
    };
}

sub recognize_expiry_date {
    my ($p) = @_;
    my $manual = trim($p->{manual_expire} || $p->{expire_date} || '');
    if ($manual ne '') {
        my $date = parse_expiry_date($manual);
        return {
            ok => JSON::PP::true,
            found => $date ? JSON::PP::true : JSON::PP::false,
            expire_date => $date || $manual,
            source => 'manual',
            detail => $date ? '已使用人工输入的有效期。' : '人工输入未解析成标准日期，请在确认页人工核对。',
        };
    }

    my $capture = capture_camera();
    return $capture unless $capture->{ok};
    my $image = "$WEB_DIR/camera/latest.jpg";
    my $cmd = $ENV{OCR_EXPIRY_CMD} || '';
    if ($cmd eq '') {
        my $vision = qwen_vision_from_image(
            $image,
            '请识别药盒侧面的生产日期、有效期、失效日期或保质期信息。只返回 JSON，字段：expiry_date，raw_text，confidence，need_user_confirm，detail。expiry_date 尽量使用 YYYY-MM-DD；如果只有年月，使用当月最后一天。',
            'expiry'
        );
        if ($vision->{ok}) {
            my $d = $vision->{data} || {};
            my $date = parse_expiry_date(join("\n", grep { defined && $_ ne '' } ($d->{expiry_date}, $d->{raw_text}, $d->{detail})));
            return {
                ok => JSON::PP::true,
                found => $date ? JSON::PP::true : JSON::PP::false,
                expire_date => $date || trim($d->{expiry_date} || ''),
                source => 'qwen3.6-flash',
                image_url => $capture->{image_url},
                detail => $date ? '已通过视觉理解识别到有效期，请核对后录入。' : ($d->{detail} || '视觉理解未解析到标准有效期，请人工核对。'),
                raw => $d,
            };
        }
        return {
            ok => JSON::PP::false,
            found => JSON::PP::false,
            source => 'qwen3.6-flash',
            image_url => $capture->{image_url},
            detail => 'Qwen3.6 有效期视觉识别调用失败：' . ($vision->{error} || 'unknown'),
        };
    }

    $cmd =~ s/\{image\}/shell_quote($image)/eg;
    my $log = "$DATA_DIR/medicine-expiry-ocr.log";
    my $rc;
    {
        local $SIG{CHLD} = 'DEFAULT';
        $rc = system('timeout', '25', 'sh', '-c', $cmd . ' >' . shell_quote($log) . ' 2>&1');
    }
    my $raw = read_text_file($log);
    my $obj = eval { decode_json($raw || '') };
    my $text = '';
    if ($obj) {
        $text = join("\n", grep { defined($_) && $_ ne '' } ($obj->{text}, $obj->{raw}, $obj->{result}));
        if (!$text && ref($obj->{lines}) eq 'ARRAY') {
            $text = join("\n", @{$obj->{lines}});
        }
    } else {
        $text = $raw || '';
    }
    my $date = parse_expiry_date($text);
    my $exit = $rc == -1 ? -1 : ($rc >> 8);
    return {
        ok => ($exit == 0 || $date) ? JSON::PP::true : JSON::PP::false,
        found => $date ? JSON::PP::true : JSON::PP::false,
        expire_date => $date || '',
        source => 'ocr',
        image_url => $capture->{image_url},
        detail => $date ? '已从药盒侧面文字识别到有效期。' : 'OCR 未解析到有效期，请调整药盒侧面位置或人工输入。',
        raw => substr($text || '', 0, 500),
        exit_code => $exit,
    };
}

sub qwen_vision_from_image {
    my ($image, $prompt, $task) = @_;
    return { ok => JSON::PP::false, error => '图片不存在' } unless $image && -s $image;
    my $api_key = dashscope_api_key();
    return { ok => JSON::PP::false, error => '未配置 DashScope API Key' } if $api_key eq '';

    my $raw = read_raw_file($image);
    my $b64 = encode_base64($raw, '');
    my $model = $ENV{QWEN_VISION_MODEL} || 'qwen3.6-flash';
    my $url = $ENV{QWEN_VISION_API_BASE} || 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions';
    my $payload = {
        model => $model,
        messages => [
            {
                role => 'system',
                content => '你是智药康护智能药柜的视觉识别模块。禁止解释，禁止推理过程，禁止 Markdown。必须只输出一个合法 JSON 对象。结果不确定时必须设置 need_user_confirm=true。',
            },
            {
                role => 'user',
                content => [
                    { type => 'text', text => $prompt },
                    { type => 'image_url', image_url => { url => 'data:image/jpeg;base64,' . $b64 } },
                ],
            },
        ],
        temperature => 0,
        max_completion_tokens => 1000,
    };
    my $json = encode_json($payload);
    my $res_file = "$DATA_DIR/qwen-vision-$task-response.json";
    my $http = https_post_json_via_openssl($url, $api_key, $json, $res_file);
    if (!$http->{ok}) {
        return { ok => JSON::PP::false, error => $http->{error} || 'HTTP request failed', status => $http->{status} || 0 };
    }
    my $text = eval { decode('UTF-8', $http->{body} || '', 1) };
    $text = $http->{body} || '' if !defined $text;
    my $obj = eval { JSON::PP->new->utf8(0)->decode($text) };
    return { ok => JSON::PP::false, error => '视觉接口返回不是 JSON', raw => substr($text || '', 0, 500) } unless $obj;
    my $content = $obj->{choices}[0]{message}{content} || '';
    my $data = parse_json_content($content);
    if (!$data) {
        my @codes = $content =~ /\b(\d{8,14})\b/g;
        my $date = parse_expiry_date($content);
        if (@codes || $date) {
            $data = {
                code_candidates => \@codes,
                expiry_date => $date || '',
                confidence => 0.45,
                need_user_confirm => JSON::PP::true,
                detail => '模型未按 JSON 输出，已从原始文本兜底提取候选信息。',
                raw_text => substr($content || '', 0, 500),
            };
        }
    }
    return { ok => JSON::PP::false, error => '模型未返回可解析 JSON', raw => substr($content || '', 0, 500) } unless $data;
    return {
        ok => JSON::PP::true,
        model => $model,
        source => 'dashscope-compatible',
        data => $data,
        raw_content => $content,
    };
}

sub parse_json_content {
    my ($s) = @_;
    $s = trim($s || '');
    $s =~ s{<think>.*?</think>}{}gis;
    $s =~ s{</think>}{}gi;
    if ($s =~ /```(?:json)?\s*(\{.*?\})\s*```/is) {
        my $obj = eval { JSON::PP->new->utf8(0)->decode($1) };
        return $obj if $obj;
    }
    $s =~ s/^```(?:json)?\s*//i;
    $s =~ s/\s*```$//;
    my $obj = eval { JSON::PP->new->utf8(0)->decode($s) };
    return $obj if $obj;
    my @starts;
    while ($s =~ /\{/g) {
        push @starts, pos($s) - 1;
    }
    for my $start (reverse @starts) {
        my $candidate = substr($s, $start);
        if ($candidate =~ /(\{.*?\})/s) {
            $obj = eval { JSON::PP->new->utf8(0)->decode($1) };
            return $obj if $obj;
        }
    }
    return undef;
}

sub parse_expiry_date {
    my ($text) = @_;
    $text = trim($text || '');
    return '' if $text eq '';
    if ($text =~ /((?:19|20)\d{2})\s*[-\.\/年]\s*(\d{1,2})\s*[-\.\/月]\s*(\d{1,2})/u) {
        return sprintf('%04d-%02d-%02d', $1, $2, $3);
    }
    if ($text =~ /((?:19|20)\d{2})(\d{2})(\d{2})/) {
        return sprintf('%04d-%02d-%02d', $1, $2, $3);
    }
    if ($text =~ /(?:EXP|Exp|有效期至|使用期限|保质期)\D{0,8}((?:19|20)\d{2})\D{0,3}(\d{1,2})(?:\D{0,3}(\d{1,2}))?/u) {
        my $day = $3 || 1;
        return sprintf('%04d-%02d-%02d', $1, $2, $day);
    }
    return '';
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
    my ($box_size) = @_;
    $box_size = normalize_box_size($box_size || '');
    my %used = map { $_->{stock} > 0 ? ($_->{slot} => 1) : () } @{list_medicines()};
    my @order = slot_order_for_size($box_size);
    for my $slot (@order) {
        return $slot unless $used{$slot};
    }
    return 23;
}

sub slot_order_for_size {
    my ($box_size) = @_;
    return (1..8, 18..23, 9..17) if $box_size eq 'large';
    return (18..23, 1..8, 9..17) if $box_size eq 'medium';
    return (9..17, 18..23, 1..8);
}

sub slot_kind {
    my ($slot) = @_;
    return '大仓' if $slot >= 1 && $slot <= 8;
    return '小仓' if $slot >= 9 && $slot <= 17;
    return '中仓' if $slot >= 18 && $slot <= 23;
    return '未知';
}

sub normalize_box_size {
    my ($s) = @_;
    $s = lc trim($s || '');
    return 'large' if $s =~ /^(large|big|大|大仓)$/;
    return 'medium' if $s =~ /^(medium|mid|中|中仓)$/;
    return 'small';
}

sub suggest_box_size {
    my ($m) = @_;
    my $text = join(' ', map { $m->{$_} || '' } qw(name dosage note manufacturer));
    return 'large' if $text =~ /(瓶|罐|口服液|颗粒|糖浆|喷雾|贴|大盒|家庭装|100\s*(?:片|粒|袋))/u;
    return 'medium' if $text =~ /(胶囊|胶囊剂|盒|板|24\s*(?:片|粒)|36\s*(?:片|粒)|48\s*(?:片|粒))/u;
    return 'small';
}

sub estimate_stock {
    my ($m) = @_;
    my $text = join(' ', map { $m->{$_} || '' } qw(dosage note name));
    if ($text =~ /(\d{1,3})\s*(?:片|粒|丸|袋|支|贴|瓶|板)/u) {
        return $1 + 0;
    }
    return 1;
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

    prepare_audio_capture();
    my $device = capture_audio_device();
    my $rate = int($ENV{ASR_RECORD_RATE} || 8000);
    my $cmd = 'arecord -q -D ' . shell_quote($device) . ' -f S16_LE -r ' . int($rate) . ' -c 1 -d ' . int($duration) . ' ' . shell_quote($out);
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
            rate => $rate,
            detail => '麦克风录音完成。',
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

sub prepare_audio_capture {
    return if $ENV{AUDIO_SKIP_CAPTURE_SETUP};
    my $card = int($ENV{AUDIO_CAPTURE_CARD} || 0);
    my $path = trim($ENV{AUDIO_CAPTURE_PATH} || 'Main Mic');
    return if $path eq '';

    my $cmd = 'amixer -c ' . $card . ' sset ' . shell_quote('Capture MIC Path') . ' ' . shell_quote($path) . ' >/dev/null 2>&1';
    system('sh', '-c', $cmd);
}

sub capture_audio_device {
    return $ENV{AUDIO_CAPTURE_DEVICE} if trim($ENV{AUDIO_CAPTURE_DEVICE} || '') ne '';
    my $cards = `arecord -l 2>/dev/null`;
    if ($cards =~ /card\s+(\d+):\s+Camera\b/i || $cards =~ /card\s+(\d+):.*USB Audio/i) {
        return 'plughw:' . $1 . ',0';
    }
    return 'plughw:0,0';
}

sub audio_asr {
    my ($p) = @_;
    my $rec = record_audio($p);
    return $rec unless $rec->{ok};
    my $helper = $ENV{ZYKH_AI_VOICE_BIN} || "$HOME_DIR/bin/zykh-ai-voice";
    return {
        ok => JSON::PP::false,
        error => 'ASR 辅助程序不存在',
        detail => '请部署 /userdata/zykh_app/bin/zykh-ai-voice',
        recording => $rec,
    } unless -x $helper;
    my $api_key = dashscope_api_key();
    return { ok => JSON::PP::false, error => '未配置 DashScope API Key', recording => $rec } if $api_key eq '';

    my $out = "$DATA_DIR/audio/asr-result.json";
    my $log = "$DATA_DIR/audio-asr.log";
    my $cmd = 'DASHSCOPE_API_KEY=' . shell_quote($api_key) . ' ' .
              shell_quote($helper) . ' asr --input ' . shell_quote($rec->{file}) .
              ' --output ' . shell_quote($out) .
              ' --model ' . shell_quote($ENV{ASR_MODEL} || 'fun-asr-flash-8k-realtime');
    my $rc;
    {
        local $SIG{CHLD} = 'DEFAULT';
        $rc = system('timeout', '35', 'sh', '-c', $cmd . ' >' . shell_quote($log) . ' 2>&1');
    }
    my $exit = $rc == -1 ? -1 : ($rc >> 8);
    my $raw = read_text_file($out);
    my $obj = eval { decode_json($raw || '') };
    if ($obj && $obj->{ok}) {
        $obj->{recording} = $rec;
        return $obj;
    }
    if ($obj && exists $obj->{text} && trim($obj->{text} || '') eq '') {
        return {
            ok => JSON::PP::true,
            text => '',
            model => $obj->{model} || ($ENV{ASR_MODEL} || 'fun-asr-flash-8k-realtime'),
            task_id => $obj->{task_id} || '',
            detail => '录音完成，但没有识别到清晰语音。',
            recording => $rec,
            exit_code => $exit,
        };
    }
    return {
        ok => JSON::PP::false,
        error => 'ASR 识别失败',
        detail => substr(read_text_file($log) || $raw || '', 0, 600),
        exit_code => $exit,
        recording => $rec,
    };
}

sub speak_text {
    my ($p) = @_;
    my $text = trim($p->{text} || '');
    return { ok => JSON::PP::false, error => '播报文本为空' } if $text eq '';
    release_audio_playback_device();
    $text = substr($text, 0, int($ENV{TTS_MAX_CHARS} || 240));
    my $vol = speaker_volume($p->{volume});
    my $tts_speed = $p->{speed} || $ENV{TTS_SPEED} || 1.32;
    $tts_speed = 1.32 unless $tts_speed =~ /^\d+(?:\.\d+)?$/;
    $tts_speed = 0.75 if $tts_speed < 0.75;
    $tts_speed = 1.45 if $tts_speed > 1.45;
    my $play = sub {
        my ($file) = @_;
        my $play_file = speed_adjusted_audio_file($file, $tts_speed);
        return speaker_setup_cmd($vol) . ' && ' . aplay_cmd($play_file);
    };

    my $dir = "$DATA_DIR/audio";
    make_path($dir) unless -d $dir;
    my $log = "$DATA_DIR/audio-speak.log";
    my $cmd = '';
    my $mode = '';

    my $helper = $ENV{ZYKH_AI_VOICE_BIN} || "$HOME_DIR/bin/zykh-ai-voice";
    my $api_key = dashscope_api_key();
    if (-x $helper && $api_key ne '') {
        my $out = "$dir/qwen-tts.wav";
        $cmd = 'DASHSCOPE_API_KEY=' . shell_quote($api_key) . ' ' .
               shell_quote($helper) . ' tts --text ' . shell_quote($text) .
               ' --output ' . shell_quote($out) .
               ' --model ' . shell_quote($ENV{TTS_MODEL} || 'qwen3-tts-instruct-flash-realtime') .
               ' --voice ' . shell_quote($ENV{TTS_VOICE} || 'Cherry') .
               ' --instructions ' . shell_quote($ENV{TTS_INSTRUCTIONS} || '面向老人，语速自然偏快，停顿简短，语气温和清晰。') .
               ' && ' . $play->($out);
        $mode = 'qwen-tts';
    } elsif ($ENV{TTS_CMD}) {
        $cmd = $ENV{TTS_CMD};
        $cmd =~ s/\{text\}/shell_quote($text)/eg;
        $mode = 'custom-tts';
    } elsif (trim(`which espeak 2>/dev/null`) ne '') {
        my $speed = int($ENV{ESPEAK_SPEED} || 175);
        $cmd = 'espeak -v zh -s ' . int($speed) . ' ' . shell_quote($text);
        $mode = 'espeak';
    } elsif (trim(`which flite 2>/dev/null`) ne '') {
        my $out = "$dir/tts.wav";
        $cmd = 'flite -t ' . shell_quote($text) . ' -o ' . shell_quote($out) . ' && ' . $play->($out);
        $mode = 'flite';
    } elsif (trim(`which aplay 2>/dev/null`) ne '') {
        my $tone = "$dir/tts-notice.wav";
        write_notice_wav($tone);
        $cmd = $play->($tone);
        $mode = 'notice-tone';
    } else {
        return { ok => JSON::PP::false, error => '板端未找到 TTS 或 aplay 播放命令', mode => 'none' };
    }

    my $rc;
    {
        local $SIG{CHLD} = 'DEFAULT';
        $rc = system('timeout', int($ENV{TTS_TIMEOUT} || 90), 'sh', '-c', $cmd . ' >' . shell_quote($log) . ' 2>&1');
    }
    my $exit = $rc == -1 ? -1 : ($rc >> 8);
    my $ok = $exit == 0 ? JSON::PP::true : JSON::PP::false;
    my $detail = $mode eq 'notice-tone'
        ? '当前板端缺少中文 TTS 引擎或 DashScope 配置，已用喇叭提示音验证播放链路。'
        : '语音播报命令已执行。';
    return {
        ok => $ok,
        mode => $mode,
        volume => $vol,
        speed => $tts_speed + 0,
        detail => $ok ? $detail : '语音播报失败：' . substr(read_text_file($log) || '', 0, 300),
        exit_code => $exit,
    };
}

sub speed_adjusted_audio_file {
    my ($file, $speed) = @_;
    return $file unless $file && -s $file;
    return $file if !$speed || abs($speed - 1.0) < 0.02;
    return $file if trim(`which ffmpeg 2>/dev/null`) eq '';
    my $out = $file;
    $out =~ s/(\.[A-Za-z0-9]+)$/\.fast$1/;
    $out = "$file.fast.wav" if $out eq $file;
    my $filter = 'atempo=' . sprintf('%.2f', $speed);
    my $cmd = 'ffmpeg -hide_banner -loglevel error -y -i ' . shell_quote($file) .
              ' -filter:a ' . shell_quote($filter) . ' ' . shell_quote($out);
    my $rc = system('timeout', '8', 'sh', '-c', $cmd);
    return -s $out && $rc == 0 ? $out : $file;
}

sub play_beep {
    my ($p) = @_;
    my $script = $ENV{BEEP_SCRIPT} || '/userdata/medical_assistant/scripts/play_beep.sh';
    return { ok => JSON::PP::false, error => '喇叭脚本不存在', script => $script } unless -f $script;
    release_audio_playback_device();
    my $vol = int($p->{volume} || $ENV{SPK_VOL} || 230);
    $vol = 0 if $vol < 0;
    $vol = 255 if $vol > 255;
    my $log = "$DATA_DIR/beep.log";
    my $cmd = 'SPK_VOL=' . int($vol) . ' sh ' . shell_quote($script);
    my $rc;
    {
        local $SIG{CHLD} = 'DEFAULT';
        $rc = system('timeout', '8', 'sh', '-c', $cmd . ' >' . shell_quote($log) . ' 2>&1');
    }
    my $exit = $rc == -1 ? -1 : ($rc >> 8);
    return {
        ok => $exit == 0 ? JSON::PP::true : JSON::PP::false,
        volume => $vol,
        detail => $exit == 0 ? '喇叭提示音播放完成' : substr(read_text_file($log) || '', 0, 500),
        exit_code => $exit,
    };
}

sub play_uploaded_audio {
    my ($p) = @_;
    my $audio = trim($p->{audio_base64} || $p->{data} || '');
    return { ok => JSON::PP::false, error => '音频数据为空' } if $audio eq '';
    release_audio_playback_device();
    $audio =~ s#^data:audio/[^;]+;base64,##;
    my $raw = eval { decode_base64($audio) };
    return { ok => JSON::PP::false, error => '音频 base64 解析失败' } if $@ || !defined $raw || length($raw) < 44;
    my $max_bytes = int($ENV{AUDIO_UPLOAD_MAX_BYTES} || 8 * 1024 * 1024);
    return { ok => JSON::PP::false, error => '音频过大' } if length($raw) > $max_bytes;

    my $dir = "$DATA_DIR/audio";
    make_path($dir) unless -d $dir;
    my $format = lc trim($p->{format} || 'wav');
    $format = 'wav' unless $format =~ /^(wav|pcm)$/;
    my $file = "$dir/relay-" . time . "-$$-" . int(rand(100000)) . ".$format";
    write_raw_file($file, $raw) or return { ok => JSON::PP::false, error => "音频写入失败：$file" };

    my $log = "$DATA_DIR/audio-play.log";
    my $vol = speaker_volume($p->{volume});
    my $setup = speaker_setup_cmd($vol);
    my $cmd = $setup . ' && ' . aplay_cmd($file);
    if ($format eq 'pcm') {
        my $rate = int($p->{rate} || 16000);
        my $channels = int($p->{channels} || 1);
        $rate = 16000 if $rate <= 0;
        $channels = 1 if $channels <= 0;
        my $device = $ENV{AUDIO_PLAY_DEVICE} || 'plughw:0,0';
        $cmd = $setup . ' && aplay -q -D ' . shell_quote($device) . ' -f S16_LE -r ' . int($rate) . ' -c ' . int($channels) . ' ' . shell_quote($file);
    }
    my $rc;
    {
        local $SIG{CHLD} = 'DEFAULT';
        $rc = system('timeout', int($ENV{AUDIO_PLAY_TIMEOUT} || 20), 'sh', '-c', $cmd . ' >' . shell_quote($log) . ' 2>&1');
    }
    my $exit = $rc == -1 ? -1 : ($rc >> 8);
    return {
        ok => $exit == 0 ? JSON::PP::true : JSON::PP::false,
        mode => 'uploaded-audio',
        file => $file,
        bytes => length($raw),
        volume => $vol,
        detail => $exit == 0 ? '已播放主机发送的音频' : substr(read_text_file($log) || '', 0, 500),
        exit_code => $exit,
    };
}

sub start_audio_pcm_stream {
    my ($p) = @_;
    my $port = int($p->{port} || $ENV{AUDIO_STREAM_PORT} || 19001);
    return { ok => JSON::PP::false, error => '音频流端口不合法' } if $port < 1024 || $port > 65535;
    my $rate = int($p->{rate} || 16000);
    my $channels = int($p->{channels} || 1);
    $rate = 16000 if $rate <= 0;
    $channels = 1 if $channels <= 0 || $channels > 2;
    my $vol = speaker_volume($p->{volume});

    stop_audio_pcm_stream();
    my $pidfile = "$DATA_DIR/audio-stream.pid";
    my $logfile = "$DATA_DIR/audio-stream.log";
    my $pid = fork();
    return { ok => JSON::PP::false, error => "fork 音频流服务失败：$!" } unless defined $pid;
    if ($pid) {
        write_text_file($pidfile, "$pid\n");
        select(undef, undef, undef, 0.25);
        return {
            ok => JSON::PP::true,
            mode => 'pcm-stream',
            port => $port,
            rate => $rate,
            channels => $channels,
            volume => $vol,
            detail => "PCM 实时音频流已启动，端口 $port",
            pid => $pid,
        };
    }

    open STDOUT, '>>', $logfile;
    open STDERR, '>>', $logfile;
    $SIG{TERM} = sub { exit 0 };
    $SIG{INT} = sub { exit 0 };
    system('sh', '-c', speaker_setup_cmd($vol));
    my $server = IO::Socket::INET->new(
        LocalHost => '0.0.0.0',
        LocalPort => $port,
        Proto     => 'tcp',
        Listen    => 1,
        Reuse     => 1,
    );
    if (!$server) {
        print now_text() . " audio stream listen failed: $!\n";
        exit 2;
    }
    print now_text() . " audio stream listening on $port rate=$rate channels=$channels volume=$vol\n";
    while (my $sock = $server->accept()) {
        $sock->autoflush(1);
        binmode($sock);
        my $device = $ENV{AUDIO_PLAY_DEVICE} || 'plughw:0,0';
        my $buffer_us = int($ENV{AUDIO_STREAM_BUFFER_US} || 80000);
        my $period_us = int($ENV{AUDIO_STREAM_PERIOD_US} || 20000);
        $buffer_us = 80000 if $buffer_us <= 0;
        $period_us = 20000 if $period_us <= 0;
        my $cmd = 'aplay -q -D ' . shell_quote($device) .
                  ' --buffer-time=' . int($buffer_us) .
                  ' --period-time=' . int($period_us) .
                  ' -f S16_LE -r ' . int($rate) .
                  ' -c ' . int($channels);
        my $aplay;
        {
            local $SIG{CHLD} = 'DEFAULT';
            open $aplay, '|-', 'sh', '-c', $cmd;
        }
        if (!$aplay) {
            print now_text() . " open aplay failed: $!\n";
            close $sock;
            next;
        }
        binmode($aplay);
        my $buf = '';
        while (read($sock, $buf, 3200)) {
            last unless print {$aplay} $buf;
        }
        close $aplay;
        close $sock;
        print now_text() . " audio stream client closed\n";
    }
    exit 0;
}

sub stop_audio_pcm_stream {
    my $pidfile = "$DATA_DIR/audio-stream.pid";
    my $pid = -f $pidfile ? read_file_trim($pidfile) : '';
    if ($pid =~ /^\d+$/) {
        kill 'TERM', int($pid);
        for (1..10) {
            last unless kill(0, int($pid));
            select(undef, undef, undef, 0.1);
        }
        kill 'KILL', int($pid) if kill(0, int($pid));
        unlink $pidfile;
        return { ok => JSON::PP::true, detail => 'PCM 实时音频流已停止', pid => int($pid) };
    }
    return { ok => JSON::PP::true, detail => '当前没有运行中的 PCM 实时音频流' };
}

sub release_audio_playback_device {
    stop_audio_pcm_stream();
    system('sh', '-c', 'killall aplay 2>/dev/null');
    select(undef, undef, undef, 0.18);
    return { ok => JSON::PP::true };
}

sub aplay_cmd {
    my ($file) = @_;
    my $device = $ENV{AUDIO_PLAY_DEVICE} || 'plughw:0,0';
    return 'aplay -q -D ' . shell_quote($device) . ' ' . shell_quote($file);
}

sub speaker_volume {
    my ($value) = @_;
    my $vol = defined($value) && "$value" ne '' ? int($value) : int($ENV{SPK_VOL} || 230);
    $vol = 0 if $vol < 0;
    $vol = 255 if $vol > 255;
    return $vol;
}

sub speaker_setup_cmd {
    my ($vol) = @_;
    my $card = int($ENV{AUDIO_CARD} || 0);
    return 'amixer -c ' . int($card) . ' cset numid=1 2 >/dev/null 2>&1 && ' .
           'amixer -c ' . int($card) . ' cset numid=5 ' . int($vol) . ',' . int($vol) . ' >/dev/null 2>&1';
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
    return { ok => JSON::PP::false, error => '仓位超出范围：1-23' } if $slot > 23;
    my $control_code = exists $p->{control_code} && "$p->{control_code}" =~ /^\d+$/
        ? int($p->{control_code})
        : cabinet_control_code($slot);
    return { ok => JSON::PP::false, error => '控制码超出范围：0-22' } if $control_code < 0 || $control_code > 22;

    my @med = sqlite_row('SELECT id,name,stock FROM medicines WHERE slot=' . int($slot) . ' ORDER BY id LIMIT 1;');
    my $name = $med[1] || "仓位$slot";
    my $stock = defined $med[2] ? int($med[2]) : -1;
    my $gpio = $ENV{"SLOT${slot}_GPIO"};
    my $uart_dev = $ENV{DISPENSE_UART} || '/dev/ttyS5';

    my $detail;
    my $result = 'success';
    if ($uart_dev && -e $uart_dev && ($ENV{DISPENSE_MODE} || 'uart') eq 'uart') {
        my $r = dispense_uart($uart_dev, $slot, $control_code);
        if ($r->{ok}) {
            $detail = $r->{detail};
        } else {
            $result = 'failed';
            $detail = $r->{error};
        }
    } elsif (defined $gpio && $gpio =~ /^\d+$/) {
        my $r = pulse_gpio($gpio, 500);
        if ($r->{ok}) {
            $detail = "GPIO$gpio 已输出 500ms 出药控制脉冲";
        } else {
            $result = 'failed';
            $detail = $r->{error};
        }
    } else {
        $detail = '未配置 UART5/GPIO，已按模拟出药记录';
    }

    # 家庭药柜按“开柜取用”记录，不按每次开柜递减整盒库存。
    add_record($name, $slot, 'dispense', $result, $detail);
    return {
        ok => ($result eq 'success' ? JSON::PP::true : JSON::PP::false),
        result => $result,
        detail => $detail,
        slot => $slot,
        control_code => $control_code,
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
    my $script = $ENV{MAX30102_SCRIPT} || '/userdata/medical_assistant/scripts/read_max30102_vitals.pl';
    my $out = $ENV{MAX30102_JSON} || '/userdata/medical_assistant/data/vital_signs.json';
    my $samples = int($ENV{MAX30102_SAMPLES} || 120);
    my $result = run_json_sensor(
        command => 'perl ' . shell_quote($script) . ' ' . int($samples) . ' ' . shell_quote($out),
        output => $out,
        timeout => 18,
        log => "$DATA_DIR/max30102-read.log",
    );

    if (!$result->{ok}) {
        return {
            ok => JSON::PP::false,
            sensor => 'MAX30102',
            error => $result->{error},
            detail => $result->{detail},
            command => $result->{command},
        };
    }

    my $raw = $result->{data} || {};
    my $vitals = {
        temperature => 0,
        heart_rate  => defined $raw->{heart_rate_bpm} ? sprintf('%.0f', $raw->{heart_rate_bpm}) + 0 : 0,
        spo2        => defined $raw->{spo2_percent} ? sprintf('%.0f', $raw->{spo2_percent}) + 0 : 0,
        systolic    => 0,
        diastolic   => 0,
        source      => 'MAX30102',
        time        => now_text(),
        finger_detected => $raw->{finger_detected} ? JSON::PP::true : JSON::PP::false,
        quality => $raw->{quality} || '',
        message => $raw->{message} || '',
        sample_count => int($raw->{sample_count} || 0),
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
        raw => $raw,
    };
}

sub dispense_uart {
    my ($dev, $slot, $control_code) = @_;
    return { ok => JSON::PP::false, error => 'UART 设备不存在：' . ($dev || '') } unless $dev && -e $dev;
    return { ok => JSON::PP::false, error => '仓位超出单字节范围' } if $slot < 1 || $slot > 255;
    $control_code = cabinet_control_code($slot) unless defined $control_code;
    return { ok => JSON::PP::false, error => '控制码超出单字节范围' } if $control_code < 0 || $control_code > 255;

    my $baud = int($ENV{DISPENSE_UART_BAUD} || 9600);
    $baud = 9600 if $baud <= 0;
    my $quoted = shell_quote($dev);
    system('sh', '-c', 'stty -F ' . $quoted . ' ' . $baud . ' cs8 -cstopb -parenb -ixon -ixoff -crtscts clocal raw -echo >/dev/null 2>&1');

    open my $fh, '>', $dev or return { ok => JSON::PP::false, error => "打开 UART 失败：$dev $!" };
    binmode($fh);
    my $command = int($control_code);
    my $payload = pack('C', $command);
    my $ok = print {$fh} $payload;
    close($fh);
    return { ok => JSON::PP::false, error => "UART 写入失败：$!" } unless $ok;

    my $hex = uc(sprintf('%02X', $command));
    write_text_file("$DATA_DIR/dispense-uart.log", now_text() . " dev=$dev baud=$baud slot=$slot control_code=$command hex=$hex\n");
    return { ok => JSON::PP::true, detail => "UART5 已发送 $slot 号仓控制字节 0x$hex（控制码 $command）" };
}

sub cabinet_control_code {
    my ($slot) = @_;
    my %map = (
        1 => 3,  2 => 2,  3 => 1,  4 => 0,
        5 => 7,  6 => 6,  7 => 5,  8 => 4,
        9 => 9,  10 => 8,
        11 => 11, 12 => 10,
        13 => 13, 14 => 12,
        15 => 16, 16 => 15, 17 => 14,
        18 => 19, 19 => 18, 20 => 17,
        21 => 22, 22 => 21, 23 => 20,
    );
    return exists $map{$slot} ? $map{$slot} : $slot - 1;
}

sub read_temperature {
    my $script = $ENV{GY614_SCRIPT} || '/userdata/medical_assistant/scripts/read_gy614_uart4.pl';
    my $out = $ENV{GY614_JSON} || '/userdata/medical_assistant/data/gy614_temp.json';
    my $dev = $ENV{GY614_UART} || '/dev/ttyS4';
    my $result = run_json_sensor(
        command => 'perl ' . shell_quote($script) . ' ' . shell_quote($dev) . ' ' . shell_quote($out),
        output => $out,
        timeout => 12,
        log => "$DATA_DIR/gy614-read.log",
    );

    if (!$result->{ok}) {
        return {
            ok => JSON::PP::false,
            sensor => 'GY-614',
            error => $result->{error},
            detail => $result->{detail},
            command => $result->{command},
        };
    }

    my $raw = $result->{data} || {};
    my $body = defined $raw->{body_temp_c} ? sprintf('%.1f', $raw->{body_temp_c}) + 0 : 0;
    add_vitals({
        temperature => $body,
        heart_rate => 0,
        spo2 => 0,
        systolic => 0,
        diastolic => 0,
        source => 'GY-614',
    }) if $body > 0;

    return {
        ok => JSON::PP::true,
        temperature => {
            body_temp_c => $body,
            target_temp_c => defined $raw->{target_temp_c} ? $raw->{target_temp_c} + 0 : 0,
            ambient_temp_c => defined $raw->{ambient_temp_c} ? $raw->{ambient_temp_c} + 0 : 0,
            source => 'GY-614',
            time => now_text(),
        },
        raw => $raw,
    };
}

sub read_all_vitals {
    my $max_script = $ENV{MAX30102_SCRIPT} || '/userdata/medical_assistant/scripts/read_max30102_vitals.pl';
    my $max_out = $ENV{MAX30102_JSON} || '/userdata/medical_assistant/data/vital_signs.json';
    my $samples = int($ENV{MAX30102_SAMPLES} || 120);
    my $max = run_json_sensor(
        command => 'perl ' . shell_quote($max_script) . ' ' . int($samples) . ' ' . shell_quote($max_out),
        output => $max_out,
        timeout => 18,
        log => "$DATA_DIR/max30102-read-all.log",
    );

    my $gy_script = $ENV{GY614_SCRIPT} || '/userdata/medical_assistant/scripts/read_gy614_uart4.pl';
    my $gy_out = $ENV{GY614_JSON} || '/userdata/medical_assistant/data/gy614_temp.json';
    my $dev = $ENV{GY614_UART} || '/dev/ttyS4';
    my $gy = run_json_sensor(
        command => 'perl ' . shell_quote($gy_script) . ' ' . shell_quote($dev) . ' ' . shell_quote($gy_out),
        output => $gy_out,
        timeout => 12,
        log => "$DATA_DIR/gy614-read-all.log",
    );

    my $max_raw = $max->{data} || {};
    my $gy_raw = $gy->{data} || {};
    my $heart_rate = defined $max_raw->{heart_rate_bpm} ? sprintf('%.0f', $max_raw->{heart_rate_bpm}) + 0 : 0;
    my $spo2 = defined $max_raw->{spo2_percent} ? sprintf('%.0f', $max_raw->{spo2_percent}) + 0 : 0;
    my $temperature = defined $gy_raw->{body_temp_c} ? sprintf('%.1f', $gy_raw->{body_temp_c}) + 0 : 0;

    add_vitals({
        temperature => $temperature,
        heart_rate => $heart_rate,
        spo2 => $spo2,
        systolic => 0,
        diastolic => 0,
        source => 'MAX30102+GY-614',
    }) if $max->{ok} || $gy->{ok};

    return {
        ok => ($max->{ok} || $gy->{ok}) ? JSON::PP::true : JSON::PP::false,
        vitals => {
            temperature => $temperature,
            heart_rate => $heart_rate,
            spo2 => $spo2,
            systolic => 0,
            diastolic => 0,
            source => 'MAX30102+GY-614',
            time => now_text(),
            finger_detected => $max_raw->{finger_detected} ? JSON::PP::true : JSON::PP::false,
            quality => $max_raw->{quality} || '',
            message => $max_raw->{message} || '',
        },
        sensors => {
            max30102 => $max,
            gy614 => $gy,
        },
    };
}

sub run_json_sensor {
    my (%args) = @_;
    my $cmd = $args{command};
    my $out = $args{output};
    my $log = $args{log} || "$DATA_DIR/sensor-read.log";
    my $timeout = int($args{timeout} || 15);
    return { ok => JSON::PP::false, error => '脚本不存在', command => $cmd } if $cmd =~ /perl\s+'?([^'\s]+)/ && !-f $1;

    my $rc;
    unlink $out if defined $out && length $out && -e $out;
    {
        local $SIG{CHLD} = 'DEFAULT';
        $rc = system('timeout', $timeout, 'sh', '-c', $cmd . ' >' . shell_quote($log) . ' 2>&1');
    }
    my $exit = $rc == -1 ? -1 : ($rc >> 8);
    my $text = -s $out ? read_text_file($out) : '';
    my $detail = substr(read_text_file($log) || '', 0, 800);
    if ($text ne '') {
        my $data = eval { decode_json(Encode::encode('UTF-8', $text)) };
        if ($data) {
            return { ok => JSON::PP::true, data => $data, exit_code => $exit, command => $cmd } if $exit == 0;
            return {
                ok => JSON::PP::false,
                data => $data,
                error => $exit == 124 ? '传感器读取超时' : '传感器读取失败',
                detail => $detail,
                exit_code => $exit,
                command => $cmd,
            };
        }
    }
    return {
        ok => JSON::PP::false,
        error => $exit == 124 ? '传感器读取超时' : '传感器读取失败',
        detail => $detail,
        exit_code => $exit,
        command => $cmd,
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
    stop_camera_preview(1);
    select(undef, undef, undef, 1.0);
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
        my $width = int($ENV{CAMERA_CAPTURE_WIDTH} || 800);
        my $height = int($ENV{CAMERA_CAPTURE_HEIGHT} || 600);
        my $buffers = int($ENV{CAMERA_CAPTURE_BUFFERS} || 10);
        $cmd = camera_capture_cmd($device, $width, $height, 30, $buffers, $out);
        my $probe = camera_link_preflight($device, $width, $height);
        return $probe unless $probe->{ok};
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
    my $probe = camera_link_preflight($device, $width, $height);
    return $probe unless $probe->{ok};
    my $logfile = "$DATA_DIR/camera-stream.log";
    my $cmd = $ENV{CAMERA_STREAM_CMD} || camera_stream_cmd($device, $width, $height, $fps, $quality, "$stream_dir/frame-%05d.jpg");
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
        for (1..10) {
            last unless kill(0, $pid);
            select(undef, undef, undef, 0.1);
        }
        system('kill', '-9', $pid) if kill(0, $pid);
        unlink $pidfile;
    }
    system('sh', '-c', "pkill -f 'multifilesink location=.*/frame-%05d.jpg' 2>/dev/null");
    select(undef, undef, undef, 0.2);
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
    select(undef, undef, undef, 1.0);
    unlink $out if -e $out;
    my $cmd = $ENV{CAMERA_CAPTURE_CMD};
    if ($cmd && $cmd =~ /\{out\}/) {
        $cmd =~ s/\{out\}/shell_quote($out)/eg;
    } elsif ($cmd) {
        $cmd .= ' ' . shell_quote($out);
    } else {
        my $device = detect_camera_device();
        my $width = int($ENV{CAMERA_CAPTURE_WIDTH} || 800);
        my $height = int($ENV{CAMERA_CAPTURE_HEIGHT} || 600);
        my $buffers = int($ENV{CAMERA_CAPTURE_BUFFERS} || 10);
        $cmd = camera_capture_cmd($device, $width, $height, 30, $buffers, $out);
        my $probe = camera_link_preflight($device, $width, $height);
        return $probe unless $probe->{ok};
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
    send_sse($client, 'meta', { model => $model, source => 'ai', context => ai_context_summary() });
    if (($ENV{AI_TRUE_STREAM} || '') ne '1') {
        my $res = ai_chat({ message => $message });
        if (!$res->{ok}) {
            send_sse($client, 'error', { error => $res->{error} || 'AI 请求失败', detail => $res->{detail} || '' });
            send_sse($client, 'done', { ok => JSON::PP::false });
            return;
        }
        my $reply = $res->{reply} || '';
        my @chars = split //, $reply;
        my $sent = '';
        while (@chars) {
            my $delta = join('', splice(@chars, 0, 12));
            $sent .= $delta;
            send_sse($client, 'delta', { delta => $delta });
            select(undef, undef, undef, 0.025);
        }
        send_sse($client, 'done', { ok => JSON::PP::true, reply => $sent });
        return;
    }
    my $payload = build_ai_payload($message, JSON::PP::true);
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

sub dashscope_api_key {
    my $api_key = trim($ENV{DASHSCOPE_API_KEY} || $ENV{ALIYUN_API_KEY} || '');
    if ($api_key eq '') {
        my $key_file = $ENV{DASHSCOPE_API_KEY_FILE} || "$DATA_DIR/dashscope-api-key.txt";
        $api_key = read_file_trim($key_file) if -s $key_file;
    }
    return $api_key;
}

sub build_ai_payload {
    my ($message, $stream) = @_;
    my $model = $ENV{AI_MODEL} || 'deepseek-v4-flash';
    my $payload = {
        model => $model,
        messages => [
            {
                role => 'system',
                content => ai_system_prompt(),
            },
            {
                role => 'user',
                content => "用户本次问题：$message\n\n请结合上面的老人档案、最近体征和本机药柜库存回答。若信息不足，先说明需要补充哪些信息。回答控制在 140 到 220 个中文字符，最多 4 条要点，适合语音播报和小屏显示。"
            },
        ],
        temperature => 0.25,
        max_tokens => 320,
        stream => $stream ? JSON::PP::true : JSON::PP::false,
    };
    my $thinking_enabled = ($ENV{AI_ENABLE_THINKING} || '0') ne '0';
    if (($ENV{AI_API_BASE} || 'https://api.deepseek.com/chat/completions') =~ /deepseek\.com/) {
        $payload->{thinking} = { type => $thinking_enabled ? 'enabled' : 'disabled' };
        $payload->{reasoning_effort} = 'high' if $thinking_enabled;
    } elsif ($thinking_enabled) {
        $payload->{enable_thinking} = JSON::PP::true;
    }
    return $payload;
}

sub ai_system_prompt {
    return join("\n", (
        '你是“智药康护”家庭智慧康护终端中的 AI 问诊助手，使用中文回答。',
        '你的工作是：解释常见健康知识、结合老人档案做风险提醒、提醒按医嘱用药、提示何时需要线下就医。',
        '严格限制：你不是医生，不能替代诊断，不能开处方，不能建议用户自行新增/停用处方药，不能自行调整剂量。',
        '药柜库存只表示家中现有药品，不能因为药柜里有某种药就建议直接服用；只能说“如果这是医生已开具/正在服用的药，请按医嘱”。',
        '遇到胸痛、呼吸困难、意识障碍、严重过敏、单侧肢体无力、血压持续超过 180/110 mmHg 等高危情况，必须建议立即急救或就医。',
        '回答格式要适合老人和家属听：先给一句结论，再列 3 到 4 条具体做法，最后说明何时必须就医。总长度控制在 140 到 220 个中文字符，避免长篇解释。',
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

sub https_post_form_via_openssl {
    my ($url, $form_body, $res_file) = @_;
    return { ok => JSON::PP::false, error => '仅支持 https:// API 地址' } unless $url =~ m{^https://([^/:]+)(?::(\d+))?(/.*)$};
    my ($host, $port, $path) = ($1, $2 || 443, $3);
    my $req_file = "$DATA_DIR/form-http-request.txt";
    my $raw_file = "$DATA_DIR/form-http-response.raw";
    my $err_file = "$DATA_DIR/form-http-error.log";
    my $body_len = length($form_body);
    my $request =
        "POST $path HTTP/1.1\r\n" .
        "Host: $host\r\n" .
        "User-Agent: zykh-app/1.0\r\n" .
        "Accept: application/json\r\n" .
        "Content-Type: application/x-www-form-urlencoded\r\n" .
        "Content-Length: $body_len\r\n" .
        "Connection: close\r\n\r\n" .
        $form_body;
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
        $rc = system('timeout', '35', 'sh', '-c', $cmd);
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
    my $cache = "$DATA_DIR/camera-device.txt";
    my $cached = read_file_trim($cache);
    return $cached if $cached && -e $cached;

    # The QSM board exposes the CSI camera on /dev/video5 in the verified setup.
    # Avoid scanning every /dev/video* node here because some ISP nodes can block.
    return '/dev/video5' if -e '/dev/video5';

    my $usb = detect_usb_camera_device();
    if ($usb) {
        write_text_file("$DATA_DIR/camera-device.txt", $usb);
        return $usb;
    }

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

sub camera_link_preflight {
    my ($device, $width, $height) = @_;
    return { ok => JSON::PP::false, error => '未找到摄像头设备' } unless $device && -e $device;

    $width = int($width || 640);
    $height = int($height || 480);
    $width = 800 if $width > 800;
    $height = 600 if $height > 600;
    my $probe = "$DATA_DIR/camera-probe.raw";
    unlink $probe if -e $probe;
    my $cmd = 'v4l2-ctl -d ' . shell_quote($device) .
              ' --set-fmt-video=width=' . $width . ',height=' . $height . ',pixelformat=NV12 ' .
              '--stream-mmap --stream-count=1 --stream-to=' . shell_quote($probe);
    my $logfile = "$DATA_DIR/camera-probe.log";
    my $rc;
    {
        local $SIG{CHLD} = 'DEFAULT';
        $rc = system('timeout', '3', 'sh', '-c', $cmd . ' >' . shell_quote($logfile) . ' 2>&1');
    }
    return { ok => JSON::PP::true, device => $device } if $rc == 0 && -s $probe;

    my $exit = $rc == -1 ? -1 : ($rc >> 8);
    my $log = read_text_file($logfile) || '';
    $log = substr($log, 0, 600);
    return {
        ok => JSON::PP::false,
        error => '摄像头硬件链路不可用，请检查外设设备摄像头排线、电源和 media pipeline',
        detail => $log,
        device => $device,
        exit_code => $exit,
        command => $cmd,
    };
}

sub detect_usb_camera_device {
    my @ff;
    my @mjpg;
    for my $dev (sort glob('/dev/video*')) {
        next if -l $dev;
        next unless -e $dev;
        my ($base) = $dev =~ m#/([^/]+)$#;
        my $name = $base ? read_file_trim("/sys/class/video4linux/$base/name") : '';
        if ($name =~ /FF Camera/i && camera_device_has_mjpg($dev)) {
            push @ff, $dev;
            next;
        }
        push @mjpg, $dev if camera_device_is_uvc($dev) || camera_device_has_mjpg($dev);
    }
    return $ff[0] if @ff;
    return $mjpg[0] if @mjpg;
    return '';
}

sub camera_device_has_mjpg {
    my ($dev) = @_;
    return 0 unless $dev && -e $dev;
    my $quoted = shell_quote($dev);
    my $formats = `v4l2-ctl -d $quoted --list-formats-ext 2>/dev/null`;
    return 1 if $formats =~ /'MJPG'/ && $formats =~ /30\.000\s+fps/;
    my ($base) = $dev =~ m#/([^/]+)$#;
    my $name = $base ? read_file_trim("/sys/class/video4linux/$base/name") : '';
    return $name =~ /FF Camera/i && $formats =~ /'MJPG'/ ? 1 : 0;
}

sub camera_device_is_uvc {
    my ($dev) = @_;
    return 0 unless $dev && -e $dev;
    my $quoted = shell_quote($dev);
    my $info = `v4l2-ctl -d $quoted --all 2>/dev/null`;
    return $info =~ /Driver name\s*:\s*uvcvideo/i || camera_device_has_mjpg($dev) ? 1 : 0;
}

sub camera_capture_cmd {
    my ($device, $width, $height, $fps, $buffers, $out) = @_;
    configure_camera_focus($device);
    if (camera_device_is_uvc($device)) {
        return 'gst-launch-1.0 -q v4l2src device=' . shell_quote($device) . ' num-buffers=' . int($buffers) . ' ' .
               '! image/jpeg,width=' . int($width) . ',height=' . int($height) . ',framerate=' . int($fps) . '/1 ' .
               '! jpegparse ! filesink location=' . shell_quote($out);
    }
    return 'gst-launch-1.0 -q v4l2src device=' . shell_quote($device) . ' num-buffers=' . int($buffers) . ' ' .
           '! video/x-raw,format=NV12,width=' . int($width) . ',height=' . int($height) . ',framerate=' . int($fps) . '/1 ' .
           camera_jpeg_encoder_fragment(80) . ' ! filesink location=' . shell_quote($out);
}

sub camera_stream_cmd {
    my ($device, $width, $height, $fps, $quality, $location) = @_;
    configure_camera_focus($device);
    if (camera_device_is_uvc($device)) {
        return 'gst-launch-1.0 -q v4l2src device=' . shell_quote($device) . ' ' .
               '! image/jpeg,width=' . int($width) . ',height=' . int($height) . ',framerate=' . int($fps) . '/1 ' .
               '! jpegparse ! multifilesink location=' . shell_quote($location) . ' max-files=3 sync=false';
    }
    return 'gst-launch-1.0 -q v4l2src device=' . shell_quote($device) . ' ' .
           '! video/x-raw,format=NV12,width=' . int($width) . ',height=' . int($height) . ',framerate=' . int($fps) . '/1 ' .
           camera_jpeg_encoder_fragment($quality) . ' ' .
           '! multifilesink location=' . shell_quote($location) . ' max-files=3 sync=false';
}

sub configure_camera_focus {
    my ($dev) = @_;
    return unless $dev && -e $dev;
    return if $ENV{CAMERA_SKIP_AUTOFOCUS};
    my $quoted = shell_quote($dev);
    my $ctrls = `v4l2-ctl -d $quoted --list-ctrls 2>/dev/null`;
    my @names = qw(focus_automatic_continuous focus_auto auto_focus continuous_auto_focus);
    for my $name (@names) {
        next unless $ctrls =~ /^\s*\Q$name\E\b/m;
        system('sh', '-c', 'v4l2-ctl -d ' . $quoted . ' --set-ctrl=' . $name . '=1 >/dev/null 2>&1');
        write_text_file("$DATA_DIR/camera-focus.txt", "$dev $name=1\n");
        return;
    }
    write_text_file("$DATA_DIR/camera-focus.txt", "$dev fixed-focus-or-no-autofocus\n") if $ctrls;
}

sub camera_jpeg_encoder_fragment {
    my ($quality) = @_;
    if (gst_element_exists('mppjpegenc')) {
        return '! mppjpegenc';
    }
    return '! videoconvert ! jpegenc quality=' . int($quality || 75);
}

sub gst_element_exists {
    my ($name) = @_;
    return 0 unless $name && $name =~ /\A[A-Za-z0-9_-]+\z/;
    my $cmd = 'gst-inspect-1.0 ' . shell_quote($name) . ' >/dev/null 2>&1';
    return system($cmd) == 0 ? 1 : 0;
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
