#!/usr/bin/env perl
use strict;
use warnings;
use utf8;
use FindBin;
use Encode qw(decode encode);
use POSIX qw(strftime);

binmode STDOUT, ':encoding(UTF-8)';

my $APP_DIR = $ENV{ZYKH_APP_DIR} || $FindBin::Bin;
my $DB_PATH = $ENV{ZYKH_DB_PATH} || "$APP_DIR/data/zykh.db";
my $OUT_DIR = $ENV{ZYKH_NATIVE_RUNTIME} || "$APP_DIR/runtime";
my $OUT_FILE = $ENV{ZYKH_NATIVE_FRAME} || "$OUT_DIR/native-home-00000.svg";

mkdir "$APP_DIR/data" unless -d "$APP_DIR/data";
mkdir $OUT_DIR unless -d $OUT_DIR;

my $now_time = strftime('%H:%M', localtime);
my $now_date = strftime('%m月%d日  星期%u', localtime);
$now_date =~ s/星期1/星期一/;
$now_date =~ s/星期2/星期二/;
$now_date =~ s/星期3/星期三/;
$now_date =~ s/星期4/星期四/;
$now_date =~ s/星期5/星期五/;
$now_date =~ s/星期6/星期六/;
$now_date =~ s/星期7/星期日/;

my ($next_time, $next_name, $next_amount) = next_plan();
my @medicines = medicines();
my $normal = 0;
my $low = 0;
my $empty = 23;
for my $m (@medicines) {
    next unless $m->{slot} >= 1 && $m->{slot} <= 23;
    $empty--;
    if ($m->{stock} > 10) {
        $normal++;
    } elsif ($m->{stock} > 0) {
        $low++;
    }
}

my $svg = svg_page();
open my $fh, '>:encoding(UTF-8)', $OUT_FILE or die "write $OUT_FILE failed: $!";
print {$fh} $svg;
close $fh;
print "$OUT_FILE\n";

sub sqlite_rows {
    my ($sql) = @_;
    return () unless -f $DB_PATH;
    open my $fh, '-|', 'sqlite3', '-separator', "\t", $DB_PATH, $sql or return ();
    my @rows;
    while (my $line = <$fh>) {
        chomp $line;
        my @cols = map { decode('UTF-8', $_) } split /\t/, $line, -1;
        push @rows, \@cols;
    }
    close $fh;
    return @rows;
}

sub next_plan {
    my @rows = sqlite_rows("SELECT time,medicine_name,amount FROM plans WHERE enabled=1 ORDER BY time LIMIT 1;");
    if (@rows && defined $rows[0]->[0] && $rows[0]->[0] ne '') {
        return ($rows[0]->[0], $rows[0]->[1] || '待设置药品', ($rows[0]->[2] || 1) . '片  口服');
    }
    return ('14:00', '阿司匹林肠溶片', '1片  口服');
}

sub medicines {
    my @rows = sqlite_rows("SELECT slot,name,stock,expire_date FROM medicines ORDER BY slot LIMIT 23;");
    my @items;
    for my $r (@rows) {
        push @items, {
            slot => int($r->[0] || 0),
            name => $r->[1] || '未命名药品',
            stock => int($r->[2] || 0),
            expire_date => $r->[3] || '--',
        };
    }
    if (!@items) {
        @items = (
            { slot => 1, name => '硝苯地平片', stock => 12, expire_date => '2026-12-31' },
            { slot => 2, name => '阿司匹林肠溶片', stock => 8, expire_date => '2026-10-31' },
            { slot => 3, name => '二甲双胍片', stock => 26, expire_date => '2027-03-31' },
        );
    }
    return @items;
}

sub e {
    my ($v) = @_;
    $v = '' unless defined $v;
    $v =~ s/&/&amp;/g;
    $v =~ s/</&lt;/g;
    $v =~ s/>/&gt;/g;
    $v =~ s/"/&quot;/g;
    return $v;
}

sub rect {
    my (%p) = @_;
    return qq(<rect x="$p{x}" y="$p{y}" width="$p{w}" height="$p{h}" rx="$p{r}" fill="$p{fill}" stroke="$p{stroke}" stroke-width="$p{sw}"/>\n);
}

sub text {
    my (%p) = @_;
    my $weight = $p{weight} || 500;
    my $anchor = $p{anchor} || 'start';
    my $fill = $p{fill} || '#142333';
    return qq(<text x="$p{x}" y="$p{y}" font-size="$p{size}" font-weight="$weight" text-anchor="$anchor" fill="$fill">$p{text}</text>\n);
}

sub slot_status {
    my ($stock) = @_;
    return ('空仓', '#ffe8ec', '#e52f34') if !defined $stock || $stock <= 0;
    return ('药量低', '#fff0d5', '#e77800') if $stock <= 10;
    return ('正常', '#dff5ec', '#069b5f');
}

sub svg_page {
    my $font = "'SimHei','Microsoft YaHei','Noto Sans CJK SC',sans-serif";
    my $s = qq(<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="600" viewBox="0 0 1024 600">\n);
    $s .= qq(<style>text{font-family:$font;dominant-baseline:auto}.muted{fill:#657586}.small{font-size:18px}.title{font-size:34px;font-weight:900}</style>\n);
    $s .= qq(<rect width="1024" height="600" fill="#f6fbfb"/>\n);
    $s .= qq(<circle cx="150" cy="70" r="160" fill="#e4f4f1"/>\n);

    $s .= qq(<path d="M38 22 L78 36 L70 92 L38 112 L6 92 L-2 36 Z" transform="translate(24,0)" fill="#008d7d"/>\n);
    $s .= text(x => 43, y => 66, size => 24, weight => 900, fill => '#fff', text => '药');
    $s .= text(x => 102, y => 44, size => 34, weight => 900, text => '智药康护');
    $s .= text(x => 104, y => 72, size => 18, fill => '#657586', text => 'QSM368ZP-WF');

    $s .= rect(x => 322, y => 22, w => 455, h => 54, r => 27, fill => '#ffffff', stroke => '#d7e4ea', sw => 1);
    $s .= qq(<circle cx="360" cy="49" r="18" fill="#eef6f8" stroke="#8fa0b2" stroke-width="2"/>\n);
    $s .= text(x => 390, y => 58, size => 24, weight => 800, text => '欢迎使用智药康护，请选择需要的服务');

    $s .= text(x => 880, y => 38, size => 19, weight => 800, fill => '#008d7d', text => '网络正常');
    $s .= text(x => 978, y => 54, size => 42, weight => 900, anchor => 'end', text => e($now_time));
    $s .= text(x => 978, y => 84, size => 19, fill => '#657586', anchor => 'end', text => e($now_date));

    $s .= rect(x => 20, y => 108, w => 300, h => 145, r => 16, fill => '#008d7d', stroke => '#008d7d', sw => 1);
    $s .= text(x => 170, y => 184, size => 78, weight => 900, anchor => 'middle', fill => '#ffffff', text => e($now_time));
    $s .= text(x => 170, y => 222, size => 28, weight => 800, anchor => 'middle', fill => '#ffffff', text => e($now_date));

    $s .= rect(x => 340, y => 108, w => 664, h => 145, r => 16, fill => '#fff8ea', stroke => '#f0c781', sw => 1);
    $s .= qq(<circle cx="378" cy="145" r="20" fill="#e77800"/>\n);
    $s .= text(x => 410, y => 153, size => 28, weight => 900, fill => '#d96f00', text => '下次服药提醒');
    $s .= text(x => 376, y => 218, size => 62, weight => 900, fill => '#e77800', text => e($next_time));
    $s .= qq(<line x1="540" y1="172" x2="540" y2="230" stroke="#ead7b7" stroke-width="2"/>\n);
    $s .= text(x => 570, y => 197, size => 31, weight => 900, text => e($next_name));
    $s .= text(x => 572, y => 228, size => 22, fill => '#657586', text => e($next_amount));
    $s .= rect(x => 812, y => 166, w => 166, h => 50, r => 14, fill => '#fff2d8', stroke => '#f0c781', sw => 1);
    $s .= text(x => 895, y => 199, size => 24, weight => 900, anchor => 'middle', fill => '#d96f00', text => '按时提醒');

    service_card(\$s, 20, 273, 300, '#008d7d', '#ffffff', '开始取药', '按计划取出药品', '药');
    service_card(\$s, 340, 273, 320, '#f4f9ff', '#1c66d4', '测量体征', '血压、心率、血氧等', '心');
    service_card(\$s, 684, 273, 320, '#f5f7ff', '#1c66d4', '拍照识别药品', '条码、溯源码、有效期', '拍');

    $s .= rect(x => 20, y => 415, w => 600, h => 124, r => 14, fill => '#ffffff', stroke => '#d8e4e9', sw => 1);
    $s .= text(x => 42, y => 452, size => 25, weight => 900, text => '药柜状态');
    $s .= text(x => 590, y => 453, size => 18, fill => '#657586', anchor => 'end', text => "共23仓  正常$normal / 低$low / 空$empty");
    my %by_slot = map { $_->{slot} => $_ } @medicines;
    for my $i (1..6) {
        my $x = 42 + ($i - 1) * 91;
        my $m = $by_slot{$i};
        my ($label, $bg, $fg) = slot_status($m ? $m->{stock} : undef);
        $s .= rect(x => $x, y => 474, w => 78, h => 46, r => 8, fill => '#fbfdfe', stroke => '#d8e4e9', sw => 1);
        $s .= text(x => $x + 39, y => 494, size => 20, weight => 900, anchor => 'middle', text => sprintf('%02d', $i));
        $s .= text(x => $x + 39, y => 515, size => 16, weight => 800, anchor => 'middle', fill => $fg, text => $label);
    }

    $s .= rect(x => 644, y => 415, w => 360, h => 124, r => 14, fill => '#eefaf7', stroke => '#bce5dc', sw => 1);
    $s .= qq(<circle cx="700" cy="477" r="32" fill="#008d7d"/>\n);
    $s .= text(x => 700, y => 488, size => 26, weight => 900, anchor => 'middle', fill => '#fff', text => 'AI');
    $s .= text(x => 752, y => 464, size => 31, weight => 900, fill => '#00786f', text => 'AI 问诊');
    $s .= text(x => 754, y => 496, size => 19, fill => '#405268', text => '调用档案、体征和药柜记忆');
    $s .= text(x => 965, y => 489, size => 36, weight => 900, anchor => 'middle', fill => '#008d7d', text => '>');

    $s .= rect(x => 20, y => 556, w => 984, h => 32, r => 10, fill => '#e8f5f2', stroke => '#e8f5f2', sw => 1);
    $s .= text(x => 44, y => 579, size => 19, weight => 900, fill => '#00786f', text => '系统已就绪，可使用 HDMI 原生界面');
    $s .= text(x => 982, y => 579, size => 17, fill => '#657586', anchor => 'end', text => '无浏览器模式 / SVG + GStreamer');

    $s .= qq(</svg>\n);
    return $s;
}

sub service_card {
    my ($out, $x, $y, $w, $fill, $fg, $title, $sub, $icon) = @_;
    $$out .= rect(x => $x, y => $y, w => $w, h => 118, r => 16, fill => $fill, stroke => '#d8e4e9', sw => 1);
    $$out .= qq(<circle cx="@{[$x + 58]}" cy="@{[$y + 59]}" r="34" fill="$fg" opacity="0.95"/>\n);
    my $icon_color = $fill eq '#008d7d' ? '#008d7d' : '#ffffff';
    $$out .= text(x => $x + 58, y => $y + 70, size => 28, weight => 900, anchor => 'middle', fill => $icon_color, text => e($icon));
    $$out .= text(x => $x + 112, y => $y + 52, size => 31, weight => 900, fill => $fg, text => e($title));
    $$out .= text(x => $x + 114, y => $y + 82, size => 18, fill => $fill eq '#008d7d' ? '#dff7f2' : '#405268', text => e($sub));
    $$out .= qq(<circle cx="@{[$x + $w - 38]}" cy="@{[$y + 59]}" r="21" fill="#ffffff" stroke="$fg" stroke-width="2"/>\n);
    $$out .= text(x => $x + $w - 38, y => $y + 70, size => 32, weight => 900, anchor => 'middle', fill => $fg, text => '>');
}
