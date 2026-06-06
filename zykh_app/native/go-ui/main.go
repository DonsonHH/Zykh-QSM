package main

import (
	"bufio"
	"bytes"
	"context"
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"image"
	"image/color"
	"image/draw"
	"image/jpeg"
	"io"
	"math"
	"mime"
	"mime/multipart"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"
	"unsafe"

	"golang.org/x/image/font"
	"golang.org/x/image/font/opentype"
	"golang.org/x/image/math/fixed"
)

const (
	defaultWidth  = 1024
	defaultHeight = 600

	fbioGetVScreenInfo = 0x4600
	fbioGetFScreenInfo = 0x4602

	evSyn = 0x00
	evKey = 0x01
	evAbs = 0x03

	synReport       = 0x00
	btnTouch        = 0x14a
	absX            = 0x00
	absY            = 0x01
	absMtPositionX  = 0x35
	absMtPositionY  = 0x36
	defaultTouchDev = "/dev/input/event4"
)

type fbBitfield struct {
	Offset   uint32
	Length   uint32
	MsbRight uint32
}

type fbVarScreenInfo struct {
	Xres         uint32
	Yres         uint32
	XresVirtual  uint32
	YresVirtual  uint32
	Xoffset      uint32
	Yoffset      uint32
	BitsPerPixel uint32
	Grayscale    uint32
	Red          fbBitfield
	Green        fbBitfield
	Blue         fbBitfield
	Transp       fbBitfield
	Nonstd       uint32
	Activate     uint32
	Height       uint32
	Width        uint32
	AccelFlags   uint32
	Pixclock     uint32
	LeftMargin   uint32
	RightMargin  uint32
	UpperMargin  uint32
	LowerMargin  uint32
	HsyncLen     uint32
	VsyncLen     uint32
	Sync         uint32
	Vmode        uint32
	Rotate       uint32
	Colorspace   uint32
	Reserved     [4]uint32
}

type fbFixScreenInfo struct {
	ID           [16]byte
	SmemStart    uintptr
	SmemLen      uint32
	Type         uint32
	TypeAux      uint32
	Visual       uint32
	XPanStep     uint16
	YPanStep     uint16
	YWrapStep    uint16
	LineLength   uint32
	MmioStart    uintptr
	MmioLen      uint32
	Accel        uint32
	Capabilities uint16
	Reserved     [2]uint16
}

type framebuffer struct {
	file   *os.File
	mem    []byte
	vari   fbVarScreenInfo
	fix    fbFixScreenInfo
	width  int
	height int
}

type renderSink interface {
	Blit(*image.RGBA)
	Close()
	Size() (int, int)
}

func (fb *framebuffer) Size() (int, int) {
	return fb.width, fb.height
}

func openFramebuffer(path string, width, height int) (*framebuffer, error) {
	f, err := os.OpenFile(path, os.O_RDWR, 0)
	if err != nil {
		return nil, err
	}
	fb := &framebuffer{file: f}
	var ioctlErrs []string
	if err := ioctl(f.Fd(), fbioGetVScreenInfo, unsafe.Pointer(&fb.vari)); err != nil {
		ioctlErrs = append(ioctlErrs, "FBIOGET_VSCREENINFO="+err.Error())
	}
	if err := ioctl(f.Fd(), fbioGetFScreenInfo, unsafe.Pointer(&fb.fix)); err != nil {
		ioctlErrs = append(ioctlErrs, "FBIOGET_FSCREENINFO="+err.Error())
	}
	fb.applySysfsFallback(path)
	if width <= 0 {
		width = int(fb.vari.Xres)
	}
	if height <= 0 {
		height = int(fb.vari.Yres)
	}
	if width <= 0 || width > int(fb.vari.XresVirtual) {
		width = defaultWidth
	}
	if height <= 0 || height > int(fb.vari.YresVirtual) {
		height = defaultHeight
	}
	fb.width = width
	fb.height = height
	size := int(fb.fix.LineLength) * fb.height
	if size <= 0 {
		size = int(fb.fix.SmemLen)
	}
	mem, err := syscall.Mmap(int(f.Fd()), 0, size, syscall.PROT_READ|syscall.PROT_WRITE, syscall.MAP_SHARED)
	if err != nil {
		_ = f.Close()
		if len(ioctlErrs) > 0 {
			return nil, fmt.Errorf("mmap framebuffer size=%d line=%d virt=%dx%d bpp=%d after %s: %w", size, fb.fix.LineLength, fb.vari.XresVirtual, fb.vari.YresVirtual, fb.vari.BitsPerPixel, strings.Join(ioctlErrs, ","), err)
		}
		return nil, fmt.Errorf("mmap framebuffer size=%d line=%d virt=%dx%d bpp=%d: %w", size, fb.fix.LineLength, fb.vari.XresVirtual, fb.vari.YresVirtual, fb.vari.BitsPerPixel, err)
	}
	fb.mem = mem
	return fb, nil
}

func (fb *framebuffer) applySysfsFallback(dev string) {
	name := filepath.Base(dev)
	base := filepath.Join("/sys/class/graphics", name)
	if fb.vari.Xres == 0 || fb.vari.Yres == 0 || fb.vari.XresVirtual == 0 || fb.vari.YresVirtual == 0 {
		if w, h, ok := readPair(filepath.Join(base, "virtual_size")); ok {
			if fb.vari.Xres == 0 {
				fb.vari.Xres = uint32(w)
			}
			if fb.vari.Yres == 0 {
				fb.vari.Yres = uint32(h)
			}
			if fb.vari.XresVirtual == 0 {
				fb.vari.XresVirtual = uint32(w)
			}
			if fb.vari.YresVirtual == 0 {
				fb.vari.YresVirtual = uint32(h)
			}
		}
	}
	if fb.vari.BitsPerPixel == 0 {
		fb.vari.BitsPerPixel = uint32(readInt(filepath.Join(base, "bits_per_pixel"), 32))
	}
	if fb.fix.LineLength == 0 {
		fb.fix.LineLength = uint32(readInt(filepath.Join(base, "stride"), int(fb.vari.XresVirtual*fb.vari.BitsPerPixel/8)))
	}
	if fb.vari.Red.Length == 0 && fb.vari.Green.Length == 0 && fb.vari.Blue.Length == 0 {
		fb.vari.Red = fbBitfield{Offset: 16, Length: 8}
		fb.vari.Green = fbBitfield{Offset: 8, Length: 8}
		fb.vari.Blue = fbBitfield{Offset: 0, Length: 8}
		fb.vari.Transp = fbBitfield{Offset: 24, Length: 8}
	}
}

func readInt(path string, fallback int) int {
	raw, err := os.ReadFile(path)
	if err != nil {
		return fallback
	}
	n, err := strconv.Atoi(strings.TrimSpace(string(raw)))
	if err != nil {
		return fallback
	}
	return n
}

func readPair(path string) (int, int, bool) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return 0, 0, false
	}
	parts := strings.Split(strings.TrimSpace(string(raw)), ",")
	if len(parts) != 2 {
		return 0, 0, false
	}
	a, errA := strconv.Atoi(strings.TrimSpace(parts[0]))
	b, errB := strconv.Atoi(strings.TrimSpace(parts[1]))
	if errA != nil || errB != nil {
		return 0, 0, false
	}
	return a, b, true
}

func (fb *framebuffer) Close() {
	if fb.mem != nil {
		_ = syscall.Munmap(fb.mem)
	}
	if fb.file != nil {
		_ = fb.file.Close()
	}
}

func (fb *framebuffer) Blit(src *image.RGBA) {
	bpp := int(fb.vari.BitsPerPixel)
	if bpp != 32 && bpp != 24 && bpp != 16 {
		return
	}
	bytesPerPixel := bpp / 8
	line := int(fb.fix.LineLength)
	xoff := int(fb.vari.Xoffset)
	yoff := int(fb.vari.Yoffset)
	maxY := min(src.Bounds().Dy(), fb.height)
	maxX := min(src.Bounds().Dx(), fb.width)
	for y := 0; y < maxY; y++ {
		rowStart := (y+yoff)*line + xoff*bytesPerPixel
		for x := 0; x < maxX; x++ {
			i := src.PixOffset(x, y)
			r, g, b, a := src.Pix[i], src.Pix[i+1], src.Pix[i+2], src.Pix[i+3]
			if a < 255 {
				r = uint8((uint16(r) * uint16(a)) / 255)
				g = uint8((uint16(g) * uint16(a)) / 255)
				b = uint8((uint16(b) * uint16(a)) / 255)
			}
			off := rowStart + x*bytesPerPixel
			switch bpp {
			case 32:
				binary.LittleEndian.PutUint32(fb.mem[off:off+4], packPixel32(r, g, b, fb.vari))
			case 24:
				p := packPixel32(r, g, b, fb.vari)
				fb.mem[off] = byte(p)
				fb.mem[off+1] = byte(p >> 8)
				fb.mem[off+2] = byte(p >> 16)
			case 16:
				p := packPixel16(r, g, b)
				binary.LittleEndian.PutUint16(fb.mem[off:off+2], p)
			}
		}
	}
}

func packPixel32(r, g, b uint8, v fbVarScreenInfo) uint32 {
	return scaleField(r, v.Red) | scaleField(g, v.Green) | scaleField(b, v.Blue) | scaleField(255, v.Transp)
}

func scaleField(value uint8, field fbBitfield) uint32 {
	if field.Length == 0 {
		return 0
	}
	maxValue := uint32((1 << field.Length) - 1)
	return ((uint32(value) * maxValue / 255) & maxValue) << field.Offset
}

func packPixel16(r, g, b uint8) uint16 {
	return uint16(r>>3)<<11 | uint16(g>>2)<<5 | uint16(b>>3)
}

type drmModeCardRes struct {
	FBIDPtr         uint64
	CRTCIDPtr       uint64
	ConnectorIDPtr  uint64
	EncoderIDPtr    uint64
	CountFBs        uint32
	CountCRTCs      uint32
	CountConnectors uint32
	CountEncoders   uint32
	MinWidth        uint32
	MaxWidth        uint32
	MinHeight       uint32
	MaxHeight       uint32
}

type drmModeModeInfo struct {
	Clock      uint32
	HDisplay   uint16
	HSyncStart uint16
	HSyncEnd   uint16
	HTotal     uint16
	HSkew      uint16
	VDisplay   uint16
	VSyncStart uint16
	VSyncEnd   uint16
	VTotal     uint16
	VScan      uint16
	VRefresh   uint32
	Flags      uint32
	Type       uint32
	Name       [32]byte
}

type drmModeGetConnector struct {
	EncodersPtr     uint64
	ModesPtr        uint64
	PropsPtr        uint64
	PropValuesPtr   uint64
	CountModes      uint32
	CountProps      uint32
	CountEncoders   uint32
	EncoderID       uint32
	ConnectorID     uint32
	ConnectorType   uint32
	ConnectorTypeID uint32
	Connection      uint32
	MMWidth         uint32
	MMHeight        uint32
	Subpixel        uint32
	Pad             uint32
}

type drmModeGetEncoder struct {
	EncoderID      uint32
	EncoderType    uint32
	CRTCID         uint32
	PossibleCRTCs  uint32
	PossibleClones uint32
}

type drmModeCreateDumb struct {
	Height uint32
	Width  uint32
	BPP    uint32
	Flags  uint32
	Handle uint32
	Pitch  uint32
	Size   uint64
}

type drmModeMapDumb struct {
	Handle uint32
	Pad    uint32
	Offset uint64
}

type drmModeDestroyDumb struct {
	Handle uint32
}

type drmModeFBCmd struct {
	FBID   uint32
	Width  uint32
	Height uint32
	Pitch  uint32
	BPP    uint32
	Depth  uint32
	Handle uint32
}

type drmModeCrtc struct {
	SetConnectorsPtr uint64
	CountConnectors  uint32
	CRTCID           uint32
	FBID             uint32
	X                uint32
	Y                uint32
	GammaSize        uint32
	ModeValid        uint32
	Mode             drmModeModeInfo
}

type drmSink struct {
	file      *os.File
	mem       []byte
	width     int
	height    int
	pitch     int
	fbID      uint32
	handle    uint32
	crtcID    uint32
	connector uint32
}

const (
	drmModeConnected     = 1
	drmModeTypePreferred = 1 << 3
)

func openDRMSink(path string, wantW, wantH int) (*drmSink, error) {
	f, err := os.OpenFile(path, os.O_RDWR, 0)
	if err != nil {
		return nil, err
	}
	s := &drmSink{file: f}
	connector, crtcID, mode, err := findDRMMode(f.Fd(), wantW, wantH)
	if err != nil {
		_ = f.Close()
		return nil, err
	}
	create := drmModeCreateDumb{
		Width:  uint32(mode.HDisplay),
		Height: uint32(mode.VDisplay),
		BPP:    32,
	}
	if err := ioctl(f.Fd(), drmReqModeCreateDumb(), unsafe.Pointer(&create)); err != nil {
		_ = f.Close()
		return nil, fmt.Errorf("create dumb buffer: %w", err)
	}
	add := drmModeFBCmd{
		Width:  create.Width,
		Height: create.Height,
		Pitch:  create.Pitch,
		BPP:    32,
		Depth:  24,
		Handle: create.Handle,
	}
	if err := ioctl(f.Fd(), drmReqModeAddFB(), unsafe.Pointer(&add)); err != nil {
		destroyDRMBuffer(f.Fd(), create.Handle)
		_ = f.Close()
		return nil, fmt.Errorf("add framebuffer: %w", err)
	}
	mapReq := drmModeMapDumb{Handle: create.Handle}
	if err := ioctl(f.Fd(), drmReqModeMapDumb(), unsafe.Pointer(&mapReq)); err != nil {
		rmDRMFB(f.Fd(), add.FBID)
		destroyDRMBuffer(f.Fd(), create.Handle)
		_ = f.Close()
		return nil, fmt.Errorf("map dumb buffer: %w", err)
	}
	mem, err := syscall.Mmap(int(f.Fd()), int64(mapReq.Offset), int(create.Size), syscall.PROT_READ|syscall.PROT_WRITE, syscall.MAP_SHARED)
	if err != nil {
		rmDRMFB(f.Fd(), add.FBID)
		destroyDRMBuffer(f.Fd(), create.Handle)
		_ = f.Close()
		return nil, fmt.Errorf("mmap dumb buffer: %w", err)
	}
	connectors := []uint32{connector}
	set := drmModeCrtc{
		SetConnectorsPtr: ptrUint32(connectors),
		CountConnectors:  1,
		CRTCID:           crtcID,
		FBID:             add.FBID,
		ModeValid:        1,
		Mode:             mode,
	}
	if err := ioctl(f.Fd(), drmReqModeSetCrtc(), unsafe.Pointer(&set)); err != nil {
		_ = syscall.Munmap(mem)
		rmDRMFB(f.Fd(), add.FBID)
		destroyDRMBuffer(f.Fd(), create.Handle)
		_ = f.Close()
		return nil, fmt.Errorf("set crtc: %w", err)
	}
	s.mem = mem
	s.width = int(create.Width)
	s.height = int(create.Height)
	s.pitch = int(create.Pitch)
	s.fbID = add.FBID
	s.handle = create.Handle
	s.crtcID = crtcID
	s.connector = connector
	return s, nil
}

func findDRMMode(fd uintptr, wantW, wantH int) (uint32, uint32, drmModeModeInfo, error) {
	var notes []string
	var res drmModeCardRes
	if err := ioctl(fd, drmReqModeGetResources(), unsafe.Pointer(&res)); err != nil {
		return 0, 0, drmModeModeInfo{}, fmt.Errorf("get resources: %w", err)
	}
	notes = append(notes, fmt.Sprintf("counts crtcs=%d connectors=%d encoders=%d", res.CountCRTCs, res.CountConnectors, res.CountEncoders))
	crtcs := make([]uint32, res.CountCRTCs)
	connectors := make([]uint32, res.CountConnectors)
	encoders := make([]uint32, res.CountEncoders)
	res.CRTCIDPtr = ptrUint32(crtcs)
	res.ConnectorIDPtr = ptrUint32(connectors)
	res.EncoderIDPtr = ptrUint32(encoders)
	if err := ioctl(fd, drmReqModeGetResources(), unsafe.Pointer(&res)); err != nil {
		return 0, 0, drmModeModeInfo{}, fmt.Errorf("get resource ids: %w", err)
	}
	notes = append(notes, fmt.Sprintf("ids crtcs=%v connectors=%v encoders=%v", crtcs, connectors, encoders))
	for _, connID := range connectors {
		conn, modes, connEncoders, err := getDRMConnector(fd, connID)
		if err != nil {
			notes = append(notes, fmt.Sprintf("connector %d error=%v", connID, err))
			continue
		}
		notes = append(notes, fmt.Sprintf("connector %d connection=%d modes=%d encoders=%v current_encoder=%d", connID, conn.Connection, len(modes), connEncoders, conn.EncoderID))
		if conn.Connection != drmModeConnected || len(modes) == 0 {
			continue
		}
		encID := conn.EncoderID
		if encID == 0 && len(connEncoders) > 0 {
			encID = connEncoders[0]
		}
		if encID == 0 {
			continue
		}
		var enc drmModeGetEncoder
		enc.EncoderID = encID
		if err := ioctl(fd, drmReqModeGetEncoder(), unsafe.Pointer(&enc)); err != nil {
			notes = append(notes, fmt.Sprintf("encoder %d error=%v", encID, err))
			continue
		}
		crtcID := enc.CRTCID
		if crtcID == 0 {
			crtcID = chooseCRTC(crtcs, enc.PossibleCRTCs)
		}
		if crtcID == 0 {
			notes = append(notes, fmt.Sprintf("encoder %d has no usable crtc possible=0x%x", encID, enc.PossibleCRTCs))
			continue
		}
		return connID, crtcID, chooseDRMMode(modes, wantW, wantH), nil
	}
	return 0, 0, drmModeModeInfo{}, fmt.Errorf("no connected DRM connector with usable mode: %s", strings.Join(notes, "; "))
}

func getDRMConnector(fd uintptr, id uint32) (drmModeGetConnector, []drmModeModeInfo, []uint32, error) {
	conn := drmModeGetConnector{ConnectorID: id}
	if err := ioctl(fd, drmReqModeGetConnector(), unsafe.Pointer(&conn)); err != nil {
		return conn, nil, nil, err
	}
	modes := make([]drmModeModeInfo, conn.CountModes)
	encoders := make([]uint32, conn.CountEncoders)
	props := make([]uint32, conn.CountProps)
	propValues := make([]uint64, conn.CountProps)
	conn.ModesPtr = ptrModeInfo(modes)
	conn.EncodersPtr = ptrUint32(encoders)
	conn.PropsPtr = ptrUint32(props)
	conn.PropValuesPtr = ptrUint64(propValues)
	if err := ioctl(fd, drmReqModeGetConnector(), unsafe.Pointer(&conn)); err != nil {
		return conn, nil, nil, err
	}
	return conn, modes, encoders, nil
}

func chooseCRTC(crtcs []uint32, possible uint32) uint32 {
	for i, id := range crtcs {
		if possible&(1<<uint(i)) != 0 {
			return id
		}
	}
	return 0
}

func chooseDRMMode(modes []drmModeModeInfo, wantW, wantH int) drmModeModeInfo {
	for _, m := range modes {
		if int(m.HDisplay) == wantW && int(m.VDisplay) == wantH {
			return m
		}
	}
	for _, m := range modes {
		if m.Type&drmModeTypePreferred != 0 {
			return m
		}
	}
	return modes[0]
}

func (d *drmSink) Size() (int, int) {
	return d.width, d.height
}

func (d *drmSink) Close() {
	if d.mem != nil {
		_ = syscall.Munmap(d.mem)
	}
	if d.file != nil {
		rmDRMFB(d.file.Fd(), d.fbID)
		destroyDRMBuffer(d.file.Fd(), d.handle)
		_ = d.file.Close()
	}
}

func (d *drmSink) Blit(src *image.RGBA) {
	maxY := min(src.Bounds().Dy(), d.height)
	maxX := min(src.Bounds().Dx(), d.width)
	for y := 0; y < maxY; y++ {
		rowStart := y * d.pitch
		for x := 0; x < maxX; x++ {
			i := src.PixOffset(x, y)
			r, g, b := src.Pix[i], src.Pix[i+1], src.Pix[i+2]
			off := rowStart + x*4
			d.mem[off] = b
			d.mem[off+1] = g
			d.mem[off+2] = r
			d.mem[off+3] = 0xff
		}
	}
}

type wlGlobal struct {
	Name    uint32
	Version uint32
}

type wlOutputInfo struct {
	ID      uint32
	Name    uint32
	Width   int
	Height  int
	Current bool
}

type waylandSink struct {
	fd            int
	mu            sync.Mutex
	width         int
	height        int
	stride        int
	mem           []byte
	file          *os.File
	registryID    uint32
	compositor    uint32
	shm           uint32
	xdgWMBase     uint32
	surface       uint32
	xdgSurface    uint32
	toplevel      uint32
	pool          uint32
	buffer        uint32
	nextID        uint32
	eventBuf      []byte
	configured    bool
	globals       map[string]wlGlobal
	outputGlobals []wlGlobal
	outputs       map[uint32]*wlOutputInfo
}

func openWaylandSink(width, height int) (*waylandSink, error) {
	path := waylandSocketPath()
	fd, err := syscall.Socket(syscall.AF_UNIX, syscall.SOCK_STREAM, 0)
	if err != nil {
		return nil, err
	}
	if err := syscall.Connect(fd, &syscall.SockaddrUnix{Name: path}); err != nil {
		_ = syscall.Close(fd)
		return nil, err
	}
	w := &waylandSink{
		fd:      fd,
		width:   width,
		height:  height,
		stride:  width * 4,
		nextID:  2,
		globals: make(map[string]wlGlobal),
		outputs: make(map[uint32]*wlOutputInfo),
	}
	if err := w.init(); err != nil {
		w.Close()
		return nil, err
	}
	go w.eventLoop()
	return w, nil
}

func waylandSocketPath() string {
	runtime := getenv("XDG_RUNTIME_DIR", "/run")
	display := getenv("WAYLAND_DISPLAY", "wayland-0")
	if strings.HasPrefix(display, "/") {
		return display
	}
	return filepath.Join(runtime, display)
}

func (w *waylandSink) init() error {
	w.registryID = w.newID()
	if err := w.send(1, 1, u32(w.registryID), nil); err != nil {
		return err
	}
	syncID := w.newID()
	if err := w.send(1, 0, u32(syncID), nil); err != nil {
		return err
	}
	if err := w.readUntil(func(id uint32, opcode uint16) bool {
		return id == syncID && opcode == 0
	}); err != nil {
		return err
	}
	comp, ok := w.globals["wl_compositor"]
	if !ok {
		return errors.New("Wayland global wl_compositor not found")
	}
	shm, ok := w.globals["wl_shm"]
	if !ok {
		return errors.New("Wayland global wl_shm not found")
	}
	xdg, ok := w.globals["xdg_wm_base"]
	if !ok {
		return errors.New("Wayland global xdg_wm_base not found")
	}
	w.compositor = w.newID()
	if err := w.bind(comp.Name, "wl_compositor", min(int(comp.Version), 4), w.compositor); err != nil {
		return err
	}
	w.shm = w.newID()
	if err := w.bind(shm.Name, "wl_shm", min(int(shm.Version), 1), w.shm); err != nil {
		return err
	}
	w.xdgWMBase = w.newID()
	if err := w.bind(xdg.Name, "xdg_wm_base", min(int(xdg.Version), 1), w.xdgWMBase); err != nil {
		return err
	}
	for _, out := range w.outputGlobals {
		id := w.newID()
		if err := w.bind(out.Name, "wl_output", min(int(out.Version), 2), id); err != nil {
			return err
		}
		w.outputs[id] = &wlOutputInfo{ID: id, Name: out.Name}
	}
	if len(w.outputs) > 0 {
		syncID = w.newID()
		if err := w.send(1, 0, u32(syncID), nil); err != nil {
			return err
		}
		if err := w.readUntil(func(id uint32, opcode uint16) bool {
			return id == syncID && opcode == 0
		}); err != nil {
			return err
		}
	}
	w.surface = w.newID()
	if err := w.send(w.compositor, 0, u32(w.surface), nil); err != nil {
		return err
	}
	w.xdgSurface = w.newID()
	if err := w.send(w.xdgWMBase, 2, append(u32(w.xdgSurface), u32(w.surface)...), nil); err != nil {
		return err
	}
	w.toplevel = w.newID()
	if err := w.send(w.xdgSurface, 1, u32(w.toplevel), nil); err != nil {
		return err
	}
	if err := w.send(w.toplevel, 2, wlString("智药康护"), nil); err != nil {
		return err
	}
	if err := w.send(w.toplevel, 3, wlString("zykh-go-ui"), nil); err != nil {
		return err
	}
	if err := w.send(w.toplevel, 11, u32(w.chooseOutput()), nil); err != nil {
		return err
	}
	if err := w.send(w.surface, 6, nil, nil); err != nil {
		return err
	}
	if err := w.readUntil(func(id uint32, opcode uint16) bool {
		return id == w.xdgSurface && opcode == 0
	}); err != nil {
		return err
	}
	if err := w.createBuffer(); err != nil {
		return err
	}
	return nil
}

func (w *waylandSink) bind(name uint32, iface string, version int, id uint32) error {
	payload := append(u32(name), wlString(iface)...)
	payload = append(payload, u32(uint32(version))...)
	payload = append(payload, u32(id)...)
	return w.send(w.registryID, 0, payload, nil)
}

func (w *waylandSink) createBuffer() error {
	size := w.stride * w.height
	f, err := os.CreateTemp("/tmp", "zykh-wayland-shm-*")
	if err != nil {
		return err
	}
	if err := f.Truncate(int64(size)); err != nil {
		_ = f.Close()
		return err
	}
	mem, err := syscall.Mmap(int(f.Fd()), 0, size, syscall.PROT_READ|syscall.PROT_WRITE, syscall.MAP_SHARED)
	if err != nil {
		_ = f.Close()
		return err
	}
	w.file = f
	w.mem = mem
	w.pool = w.newID()
	payload := append(u32(w.pool), i32(int32(size))...)
	if err := w.send(w.shm, 0, payload, []int{int(f.Fd())}); err != nil {
		return err
	}
	w.buffer = w.newID()
	payload = append(u32(w.buffer), i32(0)...)
	payload = append(payload, i32(int32(w.width))...)
	payload = append(payload, i32(int32(w.height))...)
	payload = append(payload, i32(int32(w.stride))...)
	payload = append(payload, u32(1)...)
	return w.send(w.pool, 0, payload, nil)
}

func (w *waylandSink) chooseOutput() uint32 {
	var first uint32
	for id, out := range w.outputs {
		if first == 0 {
			first = id
		}
		if out.Current && out.Width == w.width && out.Height == w.height {
			return id
		}
	}
	for id, out := range w.outputs {
		if out.Width == w.width && out.Height == w.height {
			return id
		}
	}
	return first
}

func (w *waylandSink) Size() (int, int) {
	return w.width, w.height
}

func (w *waylandSink) Close() {
	if w.mem != nil {
		_ = syscall.Munmap(w.mem)
	}
	if w.file != nil {
		name := w.file.Name()
		_ = w.file.Close()
		_ = os.Remove(name)
	}
	if w.fd >= 0 {
		_ = syscall.Close(w.fd)
		w.fd = -1
	}
}

func (w *waylandSink) Blit(src *image.RGBA) {
	maxY := min(src.Bounds().Dy(), w.height)
	maxX := min(src.Bounds().Dx(), w.width)
	for y := 0; y < maxY; y++ {
		srcRow := src.Pix[y*src.Stride:]
		dstRow := w.mem[y*w.stride:]
		for x := 0; x < maxX; x++ {
			i := x * 4
			rgba := *(*uint32)(unsafe.Pointer(&srcRow[i]))
			*(*uint32)(unsafe.Pointer(&dstRow[i])) = rgbaToXRGB(rgba)
		}
	}
	_ = w.send(w.surface, 1, append(append(u32(w.buffer), i32(0)...), i32(0)...), nil)
	_ = w.send(w.surface, 9, append(append(append(i32(0), i32(0)...), i32(int32(w.width))...), i32(int32(w.height))...), nil)
	_ = w.send(w.surface, 6, nil, nil)
}

func rgbaToXRGB(rgba uint32) uint32 {
	return 0xff000000 | ((rgba & 0x000000ff) << 16) | (rgba & 0x0000ff00) | ((rgba & 0x00ff0000) >> 16)
}

func (w *waylandSink) eventLoop() {
	_ = w.readUntil(func(uint32, uint16) bool { return false })
}

func (w *waylandSink) readUntil(done func(uint32, uint16) bool) error {
	tmp := make([]byte, 8192)
	for {
		for len(w.eventBuf) >= 8 {
			id := binary.LittleEndian.Uint32(w.eventBuf[0:4])
			opcode := binary.LittleEndian.Uint16(w.eventBuf[4:6])
			size := int(binary.LittleEndian.Uint16(w.eventBuf[6:8]))
			if size < 8 {
				return fmt.Errorf("bad wayland message size %d", size)
			}
			if len(w.eventBuf) < size {
				break
			}
			payload := append([]byte(nil), w.eventBuf[8:size]...)
			w.eventBuf = w.eventBuf[size:]
			w.handleEvent(id, opcode, payload)
			if done(id, opcode) {
				return nil
			}
		}
		n, err := syscall.Read(w.fd, tmp)
		if err != nil {
			return err
		}
		if n == 0 {
			return io.EOF
		}
		w.eventBuf = append(w.eventBuf, tmp[:n]...)
	}
}

func (w *waylandSink) handleEvent(id uint32, opcode uint16, payload []byte) {
	switch {
	case id == w.registryID && opcode == 0:
		if len(payload) < 12 {
			return
		}
		name := binary.LittleEndian.Uint32(payload[0:4])
		iface, next := readWLString(payload, 4)
		if next+4 > len(payload) {
			return
		}
		version := binary.LittleEndian.Uint32(payload[next : next+4])
		w.globals[iface] = wlGlobal{Name: name, Version: version}
		if iface == "wl_output" {
			w.outputGlobals = append(w.outputGlobals, wlGlobal{Name: name, Version: version})
		}
	case id == w.xdgWMBase && opcode == 0:
		if len(payload) >= 4 {
			serial := binary.LittleEndian.Uint32(payload[0:4])
			_ = w.send(w.xdgWMBase, 3, u32(serial), nil)
		}
	case id == w.xdgSurface && opcode == 0:
		if len(payload) >= 4 {
			serial := binary.LittleEndian.Uint32(payload[0:4])
			_ = w.send(w.xdgSurface, 4, u32(serial), nil)
			w.configured = true
		}
	default:
		if out, ok := w.outputs[id]; ok && opcode == 1 && len(payload) >= 16 {
			flags := binary.LittleEndian.Uint32(payload[0:4])
			out.Width = int(int32(binary.LittleEndian.Uint32(payload[4:8])))
			out.Height = int(int32(binary.LittleEndian.Uint32(payload[8:12])))
			out.Current = flags&1 != 0
		}
	}
}

func (w *waylandSink) send(object uint32, opcode uint16, payload []byte, fds []int) error {
	w.mu.Lock()
	defer w.mu.Unlock()
	size := 8 + len(payload)
	msg := make([]byte, size)
	binary.LittleEndian.PutUint32(msg[0:4], object)
	binary.LittleEndian.PutUint16(msg[4:6], opcode)
	binary.LittleEndian.PutUint16(msg[6:8], uint16(size))
	copy(msg[8:], payload)
	if len(fds) > 0 {
		_, err := syscall.SendmsgN(w.fd, msg, syscall.UnixRights(fds...), nil, 0)
		return err
	}
	for len(msg) > 0 {
		n, err := syscall.Write(w.fd, msg)
		if err != nil {
			return err
		}
		msg = msg[n:]
	}
	return nil
}

func (w *waylandSink) newID() uint32 {
	id := w.nextID
	w.nextID++
	return id
}

func u32(v uint32) []byte {
	buf := make([]byte, 4)
	binary.LittleEndian.PutUint32(buf, v)
	return buf
}

func i32(v int32) []byte {
	return u32(uint32(v))
}

func wlString(s string) []byte {
	raw := append([]byte(s), 0)
	length := uint32(len(raw))
	pad := (4 - len(raw)%4) % 4
	out := u32(length)
	out = append(out, raw...)
	for i := 0; i < pad; i++ {
		out = append(out, 0)
	}
	return out
}

func readWLString(payload []byte, offset int) (string, int) {
	if offset+4 > len(payload) {
		return "", len(payload)
	}
	n := int(binary.LittleEndian.Uint32(payload[offset : offset+4]))
	start := offset + 4
	end := start + n
	if end > len(payload) {
		return "", len(payload)
	}
	raw := payload[start:end]
	if len(raw) > 0 && raw[len(raw)-1] == 0 {
		raw = raw[:len(raw)-1]
	}
	next := end
	if rem := next % 4; rem != 0 {
		next += 4 - rem
	}
	return string(raw), next
}

func rmDRMFB(fd uintptr, fbID uint32) {
	if fbID != 0 {
		_ = ioctl(fd, drmReqModeRmFB(), unsafe.Pointer(&fbID))
	}
}

func destroyDRMBuffer(fd uintptr, handle uint32) {
	if handle != 0 {
		req := drmModeDestroyDumb{Handle: handle}
		_ = ioctl(fd, drmReqModeDestroyDumb(), unsafe.Pointer(&req))
	}
}

func ptrUint32(values []uint32) uint64 {
	if len(values) == 0 {
		return 0
	}
	return uint64(uintptr(unsafe.Pointer(&values[0])))
}

func ptrModeInfo(values []drmModeModeInfo) uint64 {
	if len(values) == 0 {
		return 0
	}
	return uint64(uintptr(unsafe.Pointer(&values[0])))
}

func ptrUint64(values []uint64) uint64 {
	if len(values) == 0 {
		return 0
	}
	return uint64(uintptr(unsafe.Pointer(&values[0])))
}

func drmReqModeGetResources() uintptr {
	return drmIOWR(0xA0, unsafe.Sizeof(drmModeCardRes{}))
}

func drmReqModeSetCrtc() uintptr {
	return drmIOWR(0xA2, unsafe.Sizeof(drmModeCrtc{}))
}

func drmReqModeGetEncoder() uintptr {
	return drmIOWR(0xA6, unsafe.Sizeof(drmModeGetEncoder{}))
}

func drmReqModeGetConnector() uintptr {
	return drmIOWR(0xA7, unsafe.Sizeof(drmModeGetConnector{}))
}

func drmReqModeAddFB() uintptr {
	return drmIOWR(0xAE, unsafe.Sizeof(drmModeFBCmd{}))
}

func drmReqModeRmFB() uintptr {
	var id uint32
	return drmIOWR(0xAF, unsafe.Sizeof(id))
}

func drmReqModeCreateDumb() uintptr {
	return drmIOWR(0xB2, unsafe.Sizeof(drmModeCreateDumb{}))
}

func drmReqModeMapDumb() uintptr {
	return drmIOWR(0xB3, unsafe.Sizeof(drmModeMapDumb{}))
}

func drmReqModeDestroyDumb() uintptr {
	return drmIOWR(0xB4, unsafe.Sizeof(drmModeDestroyDumb{}))
}

func drmIOWR(nr uintptr, size uintptr) uintptr {
	return (3 << 30) | (size << 16) | (uintptr('d') << 8) | nr
}

func ioctl(fd uintptr, req uintptr, arg unsafe.Pointer) error {
	_, _, errno := syscall.Syscall(syscall.SYS_IOCTL, fd, req, uintptr(arg))
	if errno != 0 {
		return errno
	}
	return nil
}

type medicine struct {
	ID         int    `json:"id"`
	Name       string `json:"name"`
	Slot       int    `json:"slot"`
	Dosage     string `json:"dosage"`
	Stock      int    `json:"stock"`
	ExpireDate string `json:"expire_date"`
}

type plan struct {
	ID           int    `json:"id"`
	Time         string `json:"time"`
	MedicineName string `json:"medicine_name"`
	Slot         int    `json:"slot"`
	Amount       int    `json:"amount"`
	Enabled      any    `json:"enabled"`
}

type statusResp struct {
	OK       bool   `json:"ok"`
	Time     string `json:"time"`
	Hostname string `json:"hostname"`
}

type medicinesResp struct {
	OK        bool       `json:"ok"`
	Medicines []medicine `json:"medicines"`
}

type plansResp struct {
	OK    bool   `json:"ok"`
	Plans []plan `json:"plans"`
}

type captureResp struct {
	OK       bool   `json:"ok"`
	Error    string `json:"error"`
	Detail   string `json:"detail"`
	ImageURL string `json:"image_url"`
}

type recognizeResp struct {
	OK          bool `json:"ok"`
	Recognition struct {
		Name       string  `json:"name"`
		Confidence float64 `json:"confidence"`
		Source     string  `json:"source"`
		Note       string  `json:"note"`
		Time       string  `json:"time"`
	} `json:"recognition"`
	Error string `json:"error"`
}

type scanMedicineResp struct {
	OK       bool   `json:"ok"`
	Code     string `json:"code"`
	Scanner  string `json:"scanner"`
	Detail   string `json:"detail"`
	ImageURL string `json:"image_url"`
	Lookup   struct {
		OK       bool `json:"ok"`
		Found    bool `json:"found"`
		Medicine struct {
			Name         string `json:"name"`
			Dosage       string `json:"dosage"`
			Manufacturer string `json:"manufacturer"`
			BatchNo      string `json:"batch_no"`
			ExpireDate   string `json:"expire_date"`
			TraceCode    string `json:"trace_code"`
			Note         string `json:"note"`
		} `json:"medicine"`
		Detail string `json:"detail"`
	} `json:"lookup"`
	Error string `json:"error"`
}

type medicineLookupResp struct {
	OK       bool   `json:"ok"`
	Found    bool   `json:"found"`
	Source   string `json:"source"`
	Medicine struct {
		Name         string `json:"name"`
		Dosage       string `json:"dosage"`
		Manufacturer string `json:"manufacturer"`
		BatchNo      string `json:"batch_no"`
		ExpireDate   string `json:"expire_date"`
		TraceCode    string `json:"trace_code"`
		Note         string `json:"note"`
	} `json:"medicine"`
	Detail string `json:"detail"`
	Error  string `json:"error"`
}

type localScanResp struct {
	OK     bool   `json:"ok"`
	Code   string `json:"code"`
	Format string `json:"format"`
	Error  string `json:"error"`
}

type autoAddResp struct {
	OK       bool `json:"ok"`
	Found    bool `json:"found"`
	Slot     int  `json:"slot"`
	Medicine struct {
		Name       string `json:"name"`
		Dosage     string `json:"dosage"`
		ExpireDate string `json:"expire_date"`
	} `json:"medicine"`
	Error string `json:"error"`
}

type expiryOCRResp struct {
	OK         bool   `json:"ok"`
	Found      bool   `json:"found"`
	ExpireDate string `json:"expire_date"`
	Source     string `json:"source"`
	ImageURL   string `json:"image_url"`
	Detail     string `json:"detail"`
	Raw        string `json:"raw"`
	Error      string `json:"error"`
}

type visualRecognizeResp struct {
	OK       bool   `json:"ok"`
	Found    bool   `json:"found"`
	Source   string `json:"source"`
	ImageURL string `json:"image_url"`
	Detail   string `json:"detail"`
	Raw      string `json:"raw"`
	Error    string `json:"error"`
	Medicine struct {
		Name       string  `json:"name"`
		Confidence float64 `json:"confidence"`
	} `json:"medicine"`
}

type aiChatResp struct {
	OK     bool   `json:"ok"`
	Reply  string `json:"reply"`
	Source string `json:"source"`
	Model  string `json:"model"`
	Error  string `json:"error"`
}

type audioRecordResp struct {
	OK       bool   `json:"ok"`
	File     string `json:"file"`
	Detail   string `json:"detail"`
	Duration int    `json:"duration"`
	Device   string `json:"device"`
	Error    string `json:"error"`
}

type audioSpeakResp struct {
	OK       bool   `json:"ok"`
	Mode     string `json:"mode"`
	Detail   string `json:"detail"`
	Error    string `json:"error"`
	ExitCode int    `json:"exit_code"`
}

type apiClient struct {
	base   string
	client *http.Client
}

func newAPI(base string) *apiClient {
	return &apiClient{
		base: strings.TrimRight(base, "/"),
		client: &http.Client{
			Timeout: 90 * time.Second,
		},
	}
}

func (a *apiClient) getJSON(path string, out any) error {
	resp, err := a.client.Get(a.base + path)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 300 {
		return fmt.Errorf("http %d", resp.StatusCode)
	}
	return json.NewDecoder(resp.Body).Decode(out)
}

func (a *apiClient) postForm(path string, values url.Values) error {
	resp, err := a.client.PostForm(a.base+path, values)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 300 {
		return fmt.Errorf("http %d", resp.StatusCode)
	}
	_, _ = io.Copy(io.Discard, resp.Body)
	return nil
}

func (a *apiClient) postFormJSON(path string, values url.Values, out any) error {
	resp, err := a.client.PostForm(a.base+path, values)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 300 {
		return fmt.Errorf("http %d", resp.StatusCode)
	}
	return json.NewDecoder(resp.Body).Decode(out)
}

type touchEvent struct {
	X      int
	Y      int
	StartX int
	StartY int
	DX     int
	DY     int
}

type inputEvent struct {
	Sec   int64
	Usec  int64
	Type  uint16
	Code  uint16
	Value int32
}

type inputAbsInfo struct {
	Value      int32
	Minimum    int32
	Maximum    int32
	Fuzz       int32
	Flat       int32
	Resolution int32
}

func eviocgabs(abs uintptr) uintptr {
	const (
		iocNRBits    = 8
		iocTypeBits  = 8
		iocSizeBits  = 14
		iocDirBits   = 2
		iocNRShift   = 0
		iocTypeShift = iocNRShift + iocNRBits
		iocSizeShift = iocTypeShift + iocTypeBits
		iocDirShift  = iocSizeShift + iocSizeBits
		iocRead      = 2
	)
	_ = iocDirBits
	return (uintptr(iocRead) << iocDirShift) |
		(uintptr(unsafe.Sizeof(inputAbsInfo{})) << iocSizeShift) |
		(uintptr('E') << iocTypeShift) |
		((0x40 + abs) << iocNRShift)
}

func readAbs(fd uintptr, code uintptr) (inputAbsInfo, error) {
	var info inputAbsInfo
	err := ioctl(fd, eviocgabs(code), unsafe.Pointer(&info))
	return info, err
}

func startTouchReader(path string, width, height int, out chan<- touchEvent) {
	go func() {
		for {
			if err := readTouch(path, width, height, out); err != nil {
				time.Sleep(time.Second)
			}
		}
	}()
}

func readTouch(path string, width, height int, out chan<- touchEvent) error {
	f, err := os.Open(path)
	if err != nil {
		return err
	}
	defer f.Close()
	xInfo, errX := readAbs(f.Fd(), absMtPositionX)
	yInfo, errY := readAbs(f.Fd(), absMtPositionY)
	if errX != nil || xInfo.Maximum <= xInfo.Minimum {
		xInfo, _ = readAbs(f.Fd(), absX)
	}
	if errY != nil || yInfo.Maximum <= yInfo.Minimum {
		yInfo, _ = readAbs(f.Fd(), absY)
	}
	if xInfo.Maximum <= xInfo.Minimum {
		xInfo.Minimum, xInfo.Maximum = 0, int32(width)
	}
	if yInfo.Maximum <= yInfo.Minimum {
		yInfo.Minimum, yInfo.Maximum = 0, int32(height)
	}
	var ev inputEvent
	var rawX, rawY int32
	var haveXY, down, tracking bool
	var startX, startY, lastX, lastY int
	for {
		if err := binary.Read(f, binary.LittleEndian, &ev); err != nil {
			return err
		}
		switch ev.Type {
		case evAbs:
			if ev.Code == absX || ev.Code == absMtPositionX {
				rawX = ev.Value
				haveXY = true
			}
			if ev.Code == absY || ev.Code == absMtPositionY {
				rawY = ev.Value
				haveXY = true
			}
		case evKey:
			if ev.Code == btnTouch {
				wasDown := down
				down = ev.Value != 0
				if down && !wasDown {
					tracking = false
				}
			}
		case evSyn:
			if ev.Code == synReport && haveXY {
				x := scaleAbs(rawX, xInfo.Minimum, xInfo.Maximum, width)
				y := scaleAbs(rawY, yInfo.Minimum, yInfo.Maximum, height)
				lastX, lastY = x, y
				if down {
					if !tracking {
						startX, startY = x, y
						tracking = true
					}
				} else {
					if !tracking {
						startX, startY = x, y
					}
					select {
					case out <- touchEvent{X: x, Y: y, StartX: startX, StartY: startY, DX: x - startX, DY: y - startY}:
					default:
					}
					tracking = false
				}
				haveXY = false
			} else if ev.Code == synReport && !down && tracking {
				select {
				case out <- touchEvent{X: lastX, Y: lastY, StartX: startX, StartY: startY, DX: lastX - startX, DY: lastY - startY}:
				default:
				}
				tracking = false
			}
		}
	}
}

func scaleAbs(v, minV, maxV int32, outMax int) int {
	if maxV <= minV {
		return 0
	}
	if v < minV {
		v = minV
	}
	if v > maxV {
		v = maxV
	}
	return int((int64(v-minV) * int64(outMax-1)) / int64(maxV-minV))
}

type app struct {
	width    int
	height   int
	appDir   string
	api      *apiClient
	fontData []byte
	font     *opentype.Font
	faces    map[int]font.Face

	mu              sync.Mutex
	page            string
	pageChanged     time.Time
	message         string
	messageUntil    time.Time
	selectedSlot    int
	dispenseSlot    int
	dispenseFilter  string
	dispenseConfirm bool
	status          statusResp
	medicines       []medicine
	plans           []plan
	lastFetch       time.Time
	wifiSSID        string
	wifiState       string
	wifiSignal      int
	wifiUpdated     time.Time
	wifiRefreshing  bool

	cameraStatus        string
	cameraName          string
	cameraMeta          string
	cameraNote          string
	cameraCode          string
	cameraExpire        string
	cameraFrame         *image.RGBA
	cameraFrameAt       time.Time
	cameraJPEG          []byte
	cameraJPEGAt        time.Time
	cameraStreamCancel  context.CancelFunc
	cameraStreamRunning bool
	cameraStreamID      int
	cameraFPS           int
	cameraAutoScan      bool
	cameraScanBusy      bool
	cameraPendingAdd    bool
	cameraPendingCode   string
	cameraPendingName   string
	cameraPendingExpire string
	cameraPendingDetail string
	cameraIgnoredCode   string
	cameraWorkflowStep  string
	cameraLastScan      time.Time
	aiQuestion          string
	aiReply             string
	aiStatus            string
	aiVoice             string
	aiMessages          []aiMessage
	aiScroll            int
	pressX              int
	pressY              int
	pressUntil          time.Time
	renderCache         *image.RGBA
	renderCacheKey      string
}

type aiMessage struct {
	Role string `json:"role"`
	Text string `json:"text"`
	Time string `json:"time"`
}

func newApp(width, height int, appDir string, api *apiClient) (*app, error) {
	fontPath := getenv("ZYKH_FONT", filepath.Join(appDir, "fonts", "simhei.ttf"))
	data, err := os.ReadFile(fontPath)
	if err != nil {
		return nil, err
	}
	tt, err := opentype.Parse(data)
	if err != nil {
		return nil, err
	}
	a := &app{
		width:              width,
		height:             height,
		appDir:             appDir,
		api:                api,
		fontData:           data,
		font:               tt,
		faces:              map[int]font.Face{},
		page:               getenv("ZYKH_START_PAGE", "home"),
		pageChanged:        time.Now(),
		selectedSlot:       1,
		dispenseSlot:       1,
		dispenseFilter:     "全部",
		cameraStatus:       "实时预览准备中",
		cameraName:         "尚未识别",
		cameraMeta:         "商品条形码",
		cameraNote:         "第一步：请将药盒商品条形码放入画面，系统会自动识别。",
		cameraCode:         "待扫描",
		cameraExpire:       "待识别",
		cameraAutoScan:     true,
		cameraWorkflowStep: "barcode",
		aiQuestion:         "我早上起来有点头晕，血压有点高，怎么办？",
		aiReply:            "您好，我会结合您的档案、体征记录和药柜库存给出参考建议。若有胸痛、呼吸困难或意识不清，请立即就医。",
		aiStatus:           "在线",
		aiVoice:            "麦克风就绪",
	}
	a.loadAIHistory()
	a.fetch()
	return a, nil
}

func (a *app) aiHistoryPath() string {
	return filepath.Join(a.appDir, "data", "ai-ui-history.json")
}

func (a *app) loadAIHistory() {
	raw, err := os.ReadFile(a.aiHistoryPath())
	if err == nil {
		var messages []aiMessage
		if json.Unmarshal(raw, &messages) == nil && len(messages) > 0 {
			a.aiMessages = messages
			last := messages[len(messages)-1]
			a.aiReply = last.Text
			return
		}
	}
	a.aiMessages = []aiMessage{
		{Role: "assistant", Text: "您好，我会结合您的健康档案、体征记录和药柜库存回答。建议仅供参考，紧急情况请及时就医。", Time: time.Now().Format("15:04")},
	}
}

func (a *app) saveAIHistoryLocked() {
	if len(a.aiMessages) > 80 {
		a.aiMessages = append([]aiMessage(nil), a.aiMessages[len(a.aiMessages)-80:]...)
	}
	path := a.aiHistoryPath()
	_ = os.MkdirAll(filepath.Dir(path), 0755)
	data, err := json.MarshalIndent(a.aiMessages, "", "  ")
	if err == nil {
		_ = os.WriteFile(path, data, 0644)
	}
}

func (a *app) face(size int) font.Face {
	if f, ok := a.faces[size]; ok {
		return f
	}
	f, err := opentype.NewFace(a.font, &opentype.FaceOptions{
		Size:    float64(size),
		DPI:     72,
		Hinting: font.HintingFull,
	})
	if err != nil {
		panic(err)
	}
	a.faces[size] = f
	return f
}

func (a *app) fetch() {
	a.mu.Lock()
	defer a.mu.Unlock()
	var st statusResp
	if err := a.api.getJSON("/api/status", &st); err == nil && st.OK {
		a.status = st
	}
	var meds medicinesResp
	if err := a.api.getJSON("/api/medicines", &meds); err == nil && meds.OK {
		a.medicines = meds.Medicines
	}
	var plans plansResp
	if err := a.api.getJSON("/api/plans", &plans); err == nil && plans.OK {
		a.plans = plans.Plans
	}
	if len(a.medicines) == 0 {
		a.medicines = []medicine{
			{Name: "硝苯地平片", Slot: 1, Dosage: "10mg", Stock: 12, ExpireDate: "2026-12-31"},
			{Name: "阿司匹林肠溶片", Slot: 2, Dosage: "100mg", Stock: 8, ExpireDate: "2026-10-31"},
			{Name: "二甲双胍片", Slot: 3, Dosage: "500mg", Stock: 26, ExpireDate: "2027-03-31"},
		}
	}
	if len(a.plans) == 0 {
		a.plans = []plan{{Time: "14:00", MedicineName: "阿司匹林肠溶片", Slot: 2, Amount: 1, Enabled: true}}
	}
	a.lastFetch = time.Now()
}

func (a *app) maybeRefreshWiFi() {
	a.mu.Lock()
	if a.wifiRefreshing || time.Since(a.wifiUpdated) < 5*time.Second {
		a.mu.Unlock()
		return
	}
	a.wifiRefreshing = true
	a.mu.Unlock()
	go a.refreshWiFi()
}

func (a *app) refreshWiFi() {
	iface, status, signalRaw := wifiStatus()
	state := valueFromLines(status, "wpa_state")
	ssid := valueFromLines(status, "ssid")
	signal := -100
	if v := valueFromLines(string(signalRaw), "RSSI"); v != "" {
		if n, err := strconv.Atoi(strings.TrimSpace(v)); err == nil {
			signal = n
		}
	}
	if state != "COMPLETED" {
		ssid = ""
		signal = -100
	}
	a.mu.Lock()
	a.wifiState = state
	if iface != "" && ssid != "" {
		a.wifiSSID = ssid
	} else {
		a.wifiSSID = ""
	}
	a.wifiSignal = signal
	a.wifiUpdated = time.Now()
	a.wifiRefreshing = false
	a.mu.Unlock()
}

func wifiStatus() (string, string, string) {
	for _, iface := range []string{"wlan0", "wlan1"} {
		statusRaw, _ := exec.Command("wpa_cli", "-i", iface, "-p", "/var/run/wpa_supplicant", "status").Output()
		status := string(statusRaw)
		if valueFromLines(status, "wpa_state") == "COMPLETED" {
			signalRaw, _ := exec.Command("wpa_cli", "-i", iface, "-p", "/var/run/wpa_supplicant", "signal_poll").Output()
			return iface, status, string(signalRaw)
		}
	}
	for _, iface := range []string{"wlan0", "wlan1"} {
		statusRaw, _ := exec.Command("wpa_cli", "-i", iface, "-p", "/var/run/wpa_supplicant", "status").Output()
		status := string(statusRaw)
		if strings.TrimSpace(status) != "" {
			signalRaw, _ := exec.Command("wpa_cli", "-i", iface, "-p", "/var/run/wpa_supplicant", "signal_poll").Output()
			return iface, status, string(signalRaw)
		}
	}
	return "", "", ""
}

func valueFromLines(raw, key string) string {
	prefix := key + "="
	for _, line := range strings.Split(raw, "\n") {
		line = strings.TrimSpace(line)
		if strings.HasPrefix(line, prefix) {
			return strings.TrimSpace(strings.TrimPrefix(line, prefix))
		}
	}
	return ""
}

func (a *app) render() *image.RGBA {
	if time.Since(a.lastFetch) > 3*time.Second {
		go a.fetch()
	}
	a.maybeRefreshWiFi()
	a.mu.Lock()
	defer a.mu.Unlock()
	now := time.Now()
	img := image.NewRGBA(image.Rect(0, 0, a.width, a.height))
	fillRect(img, 0, 0, a.width, a.height, hex(0xf6fbfb))
	cacheKey := a.renderCacheKeyLocked(now)
	var pageImg *image.RGBA
	if cacheKey != "" && a.renderCache != nil && a.renderCacheKey == cacheKey {
		pageImg = a.renderCache
	} else {
		pageImg = image.NewRGBA(image.Rect(0, 0, a.width, a.height))
		fillRect(pageImg, 0, 0, a.width, a.height, hex(0xf6fbfb))
		if a.page == "camera" {
			frame, running, fps := a.cameraFrame, a.cameraStreamRunning, a.cameraFPS
			a.cameraFrame, a.cameraStreamRunning, a.cameraFPS = nil, false, 0
			a.renderPage(pageImg)
			a.cameraFrame, a.cameraStreamRunning, a.cameraFPS = frame, running, fps
		} else {
			a.renderPage(pageImg)
		}
		if cacheKey != "" {
			a.renderCache = pageImg
			a.renderCacheKey = cacheKey
		} else {
			a.renderCache = nil
			a.renderCacheKey = ""
		}
	}
	elapsed := time.Since(a.pageChanged)
	if elapsed < 260*time.Millisecond {
		progress := float64(elapsed) / float64(260*time.Millisecond)
		offset := int(float64(a.width) * (1 - progress) * 0.08)
		draw.Draw(img, image.Rect(offset, 0, offset+a.width, a.height), pageImg, image.Point{}, draw.Src)
		fillRect(img, 0, 0, offset, a.height, hex(0xf6fbfb))
		line(img, offset, 0, offset, a.height, hex(0xcfe1ef), 1)
	} else {
		draw.Draw(img, img.Bounds(), pageImg, image.Point{}, draw.Src)
	}
	if a.page == "camera" && elapsed >= 260*time.Millisecond {
		a.renderCameraLiveOverlay(img)
	}
	if a.message != "" && time.Now().Before(a.messageUntil) {
		a.toast(img, a.message)
	}
	a.renderTouchFeedback(img)
	return img
}

func (a *app) renderCacheKeyLocked(now time.Time) string {
	if a.page == "ai" {
		return ""
	}
	var b strings.Builder
	fmt.Fprintf(&b, "%s|%s|%s|%s|%d|%s|%d|%d|%s|%t|",
		a.page,
		now.Format("200601021504"),
		a.status.Time,
		a.wifiState,
		a.wifiSignal,
		a.wifiSSID,
		a.selectedSlot,
		a.dispenseSlot,
		a.dispenseFilter,
		a.dispenseConfirm,
	)
	for _, m := range a.medicines {
		fmt.Fprintf(&b, "m:%d:%s:%d:%d:%s;", m.ID, m.Name, m.Slot, m.Stock, m.ExpireDate)
	}
	for _, p := range a.plans {
		fmt.Fprintf(&b, "p:%d:%s:%s:%d:%d;", p.ID, p.Time, p.MedicineName, p.Slot, p.Amount)
	}
	return b.String()
}

func (a *app) renderCameraLiveOverlay(img *image.RGBA) {
	fillRect(img, 438, 104, 170, 26, hex(0xffffff))
	fpsText := "等待视频流"
	if a.cameraStreamRunning {
		fpsText = fmt.Sprintf("实时预览 %d fps", a.cameraFPS)
	}
	a.textRight(img, 608, 122, 16, fpsText, hex(0x008d7d), true)
	if a.cameraFrame != nil {
		drawImageCover(img, a.cameraFrame, 46, 148, 558, 292)
	}
	scanY := 170 + int(time.Now().UnixMilli()/22)%244
	line(img, 66, scanY, 584, scanY, hex(0x00d2c3), 2)
	line(img, 66, scanY+3, 584, scanY+3, hex(0x65efe3), 1)
}

func (a *app) renderTouchFeedback(img *image.RGBA) {
	if a.pressX <= 0 || a.pressY <= 0 {
		return
	}
	left := time.Until(a.pressUntil)
	if left <= 0 {
		return
	}
	progress := 1 - float64(left)/float64(180*time.Millisecond)
	if progress < 0 {
		progress = 0
	}
	if progress > 1 {
		progress = 1
	}
	radius := 18 + int(progress*26)
	alpha := uint8(74 - int(progress*48))
	circleAlpha(img, a.pressX, a.pressY, radius, color.RGBA{R: 0, G: 141, B: 125, A: alpha})
	circleAlpha(img, a.pressX, a.pressY, max(8, radius-12), color.RGBA{R: 255, G: 255, B: 255, A: alpha / 2})
}

func (a *app) renderPage(img *image.RGBA) {
	switch a.page {
	case "cabinet":
		a.renderCabinet(img)
	case "dispense":
		a.renderDispense(img)
	case "camera":
		a.renderCamera(img)
	case "ai":
		a.renderAI(img)
	default:
		a.renderHome(img)
	}
}

func (a *app) nextPlan() plan {
	for _, p := range a.plans {
		if planEnabled(p) {
			return p
		}
	}
	return plan{Time: "--:--", MedicineName: "暂无用药计划", Amount: 0}
}

func planEnabled(p plan) bool {
	switch v := p.Enabled.(type) {
	case bool:
		return v
	case float64:
		return v != 0
	case string:
		return v != "" && v != "0" && strings.ToLower(v) != "false"
	case nil:
		return true
	default:
		return true
	}
}

func (a *app) counts() (normal, low, empty int) {
	empty = 23
	for _, m := range a.medicines {
		if m.Slot < 1 || m.Slot > 23 {
			continue
		}
		empty--
		if m.Stock > 10 {
			normal++
		} else if m.Stock > 0 {
			low++
		}
	}
	return
}

func (a *app) renderHome(img *image.RGBA) {
	now := time.Now()
	timeText := now.Format("15:04")
	dateText := chineseDate(now)
	next := a.nextPlan()
	normal, low, empty := a.counts()

	a.shield(img, 22, 12, 56, 58, "药")
	a.text(img, 82, 40, 29, "智药康护", hex(0x142333), true)
	a.text(img, 84, 64, 16, "QSM368ZP-WF", hex(0x607082), false)

	roundRect(img, 300, 14, 492, 48, 24, hex(0xffffff), hex(0xd8e4e9), 1)
	a.text(img, 388, 45, 22, "欢迎使用智药康护，请选择需要的服务", hex(0x142333), true)
	circle(img, 358, 38, 17, hex(0xf3f8fa))
	a.textCenter(img, 358, 47, 17, "音", hex(0x8fa0b2), true)

	a.renderWifiIndicator(img, 872, 24, 40)
	a.textRight(img, 1004, 44, 34, timeText, hex(0x142333), true)
	a.textRight(img, 1004, 72, 17, dateText, hex(0x607082), false)

	roundRect(img, 20, 84, 326, 138, 14, hex(0x008d7d), hex(0x008d7d), 1)
	a.textCenter(img, 183, 153, 72, timeText, hex(0xffffff), true)
	a.textCenter(img, 183, 206, 28, dateText, hex(0xffffff), true)

	roundRect(img, 360, 84, 644, 138, 14, hex(0xfff8ea), hex(0xf0c781), 1)
	circle(img, 400, 116, 16, hex(0xe77800))
	a.text(img, 424, 128, 26, "下次服药提醒", hex(0xd96f00), true)
	a.text(img, 386, 194, 54, next.Time, hex(0xe77800), true)
	line(img, 552, 148, 552, 204, hex(0xead7b7), 2)
	a.text(img, 584, 170, 28, next.MedicineName, hex(0x142333), true)
	a.text(img, 584, 202, 22, fmt.Sprintf("%d片 口服", max(next.Amount, 1)), hex(0x607082), false)
	roundRect(img, 816, 142, 168, 56, 12, hex(0xfff2d8), hex(0xf0c781), 1)
	a.textCenter(img, 900, 176, 22, "按时提醒", hex(0xd96f00), true)

	a.service(img, 20, 236, 326, 122, hex(0x008d7d), hex(0xffffff), "开始取药", "按计划取出药品", "药")
	a.service(img, 360, 236, 310, 122, hex(0xf4f9ff), hex(0x1c66d4), "测量体征", "血压、心率、血氧", "测")
	a.service(img, 686, 236, 318, 122, hex(0xf5f7ff), hex(0x1c66d4), "拍照识别", "条码、溯源码", "拍")

	roundRect(img, 20, 376, 650, 134, 14, hex(0xffffff), hex(0xd8e4e9), 1)
	a.text(img, 38, 414, 24, "药柜状态", hex(0x142333), true)
	roundRect(img, 318, 388, 58, 34, 17, hex(0xe7f8f4), hex(0xbce5dc), 1)
	a.textCenter(img, 347, 411, 16, "更多", hex(0x008d7d), true)
	a.textRight(img, 650, 411, 17, fmt.Sprintf("共23仓 / 正常%d / 低%d / 空%d", normal, low, empty), hex(0x607082), false)
	for i := 1; i <= 6; i++ {
		x := 38 + (i-1)*100
		a.slotSmall(img, x, 430, 84, 50, i, a.medBySlot(i))
	}

	roundRect(img, 686, 376, 318, 92, 14, hex(0xfff7f8), hex(0xf6bdc2), 1)
	circle(img, 738, 422, 34, hex(0xe62f34))
	a.textCenter(img, 738, 435, 28, "AI", hex(0xffffff), true)
	a.text(img, 806, 410, 29, "AI 问诊", hex(0xd91f2b), true)
	a.text(img, 808, 440, 17, "结合档案和体征咨询", hex(0x405268), false)
	a.textCenter(img, 970, 435, 22, ">", hex(0xe62f34), true)

	roundRect(img, 20, 552, 984, 36, 10, hex(0xe8f5f2), hex(0xe8f5f2), 1)
	host := a.status.Hostname
	if host == "" {
		host = "rockchip"
	}
	a.text(img, 60, 577, 19, host+" 已就绪，可以开始使用", hex(0x00786f), true)
	a.textRight(img, 982, 577, 17, "Go 原生 UI", hex(0x657586), false)
}

func (a *app) renderCabinet(img *image.RGBA) {
	normal, low, empty := a.counts()
	roundRect(img, 16, 12, 86, 38, 9, hex(0x008d7d), hex(0x008d7d), 1)
	a.textCenter(img, 59, 38, 16, "返回首页", hex(0xffffff), true)
	a.text(img, 122, 35, 31, "23 仓药柜布局", hex(0x142333), true)
	a.text(img, 122, 58, 16, "大仓 8 个 / 中仓 6 个 / 小仓 9 个，点击仓位查看药品信息", hex(0x657586), false)
	roundRect(img, 838, 8, 170, 48, 9, hex(0xffffff), hex(0xd8e4e9), 1)
	a.textCenter(img, 923, 31, 17, fmt.Sprintf("正常 %d / 低 %d / 空 %d", normal, low, empty), hex(0x008d7d), true)
	a.textCenter(img, 923, 52, 14, "共 23 仓", hex(0x657586), false)

	roundRect(img, 16, 70, 730, 510, 8, hex(0xfffdf3), hex(0x2b2f33), 2)
	a.drawCabinetSlots(img)

	roundRect(img, 760, 70, 248, 510, 12, hex(0xffffff), hex(0xd8e4e9), 1)
	slot := a.selectedSlot
	item := a.medBySlot(slot)
	kind := slotKind(slot)
	a.text(img, 782, 116, 26, fmt.Sprintf("%02d 号%s", slot, kind), hex(0x142333), true)
	if item == nil {
		a.text(img, 782, 154, 18, "当前仓位未绑定药品。", hex(0x657586), false)
		a.text(img, 782, 184, 18, "可通过扫码识别或后台录入。", hex(0x657586), false)
	} else {
		status, _, fg := stockStatus(item)
		a.kv(img, 782, 162, "药品", item.Name)
		a.kv(img, 782, 206, "规格", item.Dosage)
		a.kv(img, 782, 250, "余量", fmt.Sprintf("%d 片", item.Stock))
		a.kv(img, 782, 294, "有效期", item.ExpireDate)
		a.kvColor(img, 782, 338, "状态", status, fg)
	}
	a.text(img, 782, 518, 17, "触摸仓位可查看详情", hex(0x657586), false)
}

func (a *app) renderDispense(img *image.RGBA) {
	a.pageHeader(img, "选择取药", "按药品或仓位选择，确认后打开对应药柜")
	filters := []string{"全部", "降压", "阿司匹林", "二甲", "低库存"}
	for i, f := range filters {
		x := 36 + i*118
		bg, fg := hex(0xf7fbff), hex(0x405268)
		if a.dispenseFilter == f {
			bg, fg = hex(0x008d7d), hex(0xffffff)
		}
		roundRect(img, x, 86, 102, 38, 12, bg, hex(0xbcd8e8), 1)
		a.textCenter(img, x+51, 111, 17, f, fg, true)
	}
	roundRect(img, 650, 86, 330, 38, 12, hex(0xffffff), hex(0xd8e4e9), 1)
	a.text(img, 672, 111, 16, "搜索：触摸左侧分类或右侧仓位快速定位药品", hex(0x657586), false)

	roundRect(img, 24, 142, 598, 382, 12, hex(0xffffff), hex(0xd8e4e9), 1)
	a.text(img, 48, 178, 23, "药品列表", hex(0x142333), true)
	filtered := a.filteredMedicines()
	if len(filtered) == 0 {
		a.text(img, 56, 230, 18, "没有匹配药品，请切换筛选条件。", hex(0x657586), false)
	}
	for i, m := range filtered {
		if i >= 6 {
			break
		}
		y := 198 + i*52
		selected := m.Slot == a.dispenseSlot
		bg := colorFor(selected, hex(0xe7f8f4), hex(0xfbfdfe))
		st := colorFor(selected, hex(0x008d7d), hex(0xd8e4e9))
		roundRect(img, 48, y, 548, 44, 10, bg, st, 1)
		a.text(img, 66, y+28, 18, fmt.Sprintf("%02d仓  %s", m.Slot, clipText(m.Name, 12)), hex(0x142333), true)
		a.textRight(img, 456, y+28, 15, clipText(m.Dosage, 8), hex(0x657586), false)
		status, _, fg := stockStatus(&m)
		roundRect(img, 500, y+10, 72, 24, 12, hex(0xf3f8fa), hex(0xd8e4e9), 1)
		a.textCenter(img, 536, y+28, 14, fmt.Sprintf("%s/%d", status, m.Stock), fg, true)
	}

	roundRect(img, 646, 142, 350, 382, 12, hex(0xffffff), hex(0xd8e4e9), 1)
	a.text(img, 670, 178, 23, "按仓位选择", hex(0x142333), true)
	for i := 1; i <= 23; i++ {
		col := (i - 1) % 6
		row := (i - 1) / 6
		x := 668 + col*52
		y := 196 + row*48
		item := a.medBySlot(i)
		bg := hex(0xfbfdfe)
		st := hex(0xd8e4e9)
		fg := hex(0x142333)
		if item == nil {
			fg = hex(0x95a3b2)
		}
		if i == a.dispenseSlot {
			bg, st, fg = hex(0x008d7d), hex(0x008d7d), hex(0xffffff)
		}
		roundRect(img, x, y, 42, 36, 8, bg, st, 1)
		a.textCenter(img, x+21, y+24, 15, fmt.Sprintf("%02d", i), fg, true)
	}
	item := a.medBySlot(a.dispenseSlot)
	roundRect(img, 670, 406, 304, 94, 12, hex(0xf8fcfc), hex(0xcfe1ef), 1)
	if item == nil {
		a.text(img, 694, 444, 20, fmt.Sprintf("%02d 仓为空", a.dispenseSlot), hex(0x657586), true)
		a.text(img, 694, 474, 15, "请选择有药品的仓位。", hex(0x95a3b2), false)
	} else {
		a.text(img, 694, 438, 21, clipText(item.Name, 12), hex(0x142333), true)
		a.text(img, 694, 468, 15, fmt.Sprintf("%02d仓 / 余量 %d / 有效期 %s", item.Slot, item.Stock, clipText(item.ExpireDate, 8)), hex(0x657586), false)
	}

	roundRect(img, 24, 542, 470, 42, 12, hex(0xe8f5f2), hex(0xe8f5f2), 1)
	a.text(img, 48, 569, 17, "建议先核对药名、仓位和余量，再确认打开药柜。", hex(0x00786f), true)
	canDispense := item != nil && item.Stock > 0
	btnBg := colorFor(canDispense, hex(0x008d7d), hex(0xc8d4dc))
	roundRect(img, 688, 538, 292, 48, 14, btnBg, btnBg, 1)
	btnText := "库存不足，不能取药"
	if canDispense {
		btnText = "确认取出当前药品"
	}
	a.textCenter(img, 834, 569, 20, btnText, hex(0xffffff), true)
	if a.dispenseConfirm {
		a.renderDispenseConfirm(img)
	}
}

func (a *app) filteredMedicines() []medicine {
	var out []medicine
	for _, m := range a.medicines {
		if a.matchDispenseFilter(m) {
			out = append(out, m)
		}
	}
	return out
}

func (a *app) matchDispenseFilter(m medicine) bool {
	f := a.dispenseFilter
	name := m.Name + " " + m.Dosage
	switch f {
	case "", "全部":
		return true
	case "降压":
		return strings.Contains(name, "平") || strings.Contains(name, "沙坦") || strings.Contains(name, "普利") || strings.Contains(name, "地平")
	case "阿司匹林":
		return strings.Contains(name, "阿司匹林")
	case "二甲":
		return strings.Contains(name, "二甲") || strings.Contains(name, "双胍")
	case "低库存":
		return m.Stock > 0 && m.Stock <= 10
	default:
		return strings.Contains(name, f) || fmt.Sprintf("%02d", m.Slot) == f
	}
}

func (a *app) renderDispenseConfirm(img *image.RGBA) {
	item := a.medBySlot(a.dispenseSlot)
	fillRectAlpha(img, 0, 0, a.width, a.height, color.RGBA{R: 18, G: 35, B: 48, A: 132})
	roundRect(img, 286, 172, 452, 248, 16, hex(0xffffff), hex(0xbce5dc), 2)
	a.text(img, 334, 220, 27, "确认打开药柜", hex(0x142333), true)
	if item == nil {
		a.text(img, 334, 266, 18, fmt.Sprintf("%02d 仓为空，不能取药。", a.dispenseSlot), hex(0xe52f34), true)
	} else if item.Stock <= 0 {
		a.text(img, 334, 266, 18, fmt.Sprintf("%02d 仓库存不足，不能取药。", a.dispenseSlot), hex(0xe52f34), true)
	} else {
		a.text(img, 334, 262, 21, clipText(item.Name, 14), hex(0x142333), true)
		a.text(img, 334, 296, 17, fmt.Sprintf("%02d 仓 / 余量 %d / %s", item.Slot, item.Stock, item.Dosage), hex(0x657586), false)
		a.text(img, 334, 326, 15, "确认后将触发对应仓位出药控制。", hex(0xe77800), false)
	}
	roundRect(img, 334, 356, 150, 42, 12, hex(0xf4f9ff), hex(0xadc9ee), 1)
	a.textCenter(img, 409, 383, 18, "取消", hex(0x1c66d4), true)
	roundRect(img, 548, 356, 150, 42, 12, hex(0x008d7d), hex(0x008d7d), 1)
	a.textCenter(img, 623, 383, 18, "确认取药", hex(0xffffff), true)
}

func (a *app) renderAI(img *image.RGBA) {
	a.pageHeader(img, "AI 健康咨询终端", "语音问诊、档案记忆和用药建议")

	roundRect(img, 20, 82, 252, 480, 12, hex(0xffffff), hex(0xd8e4e9), 1)
	circle(img, 66, 128, 30, hex(0xe7f8f4))
	a.textCenter(img, 66, 139, 24, "档", hex(0x008d7d), true)
	a.text(img, 104, 120, 24, "演示用户", hex(0x142333), true)
	a.text(img, 106, 148, 16, "72 岁  男  本机用户", hex(0x607082), false)
	a.sectionLabel(img, 38, 198, "慢性疾病")
	a.chip(img, 38, 214, 76, "高血压", hex(0xf7fbff), hex(0x405268))
	a.chip(img, 122, 214, 76, "冠心病", hex(0xf7fbff), hex(0x405268))
	a.chip(img, 38, 252, 96, "2 型糖尿病", hex(0xf7fbff), hex(0x405268))
	a.sectionLabel(img, 38, 314, "最新体征")
	a.kvMini(img, 38, 342, "体温", "36.6 °C")
	a.kvMini(img, 38, 380, "心率", "75 次/分")
	a.kvMini(img, 38, 418, "血氧", "96 %")
	a.sectionLabel(img, 38, 484, "药柜可用")
	a.text(img, 38, 524, 15, "硝苯地平片、阿司匹林肠溶片", hex(0x405268), false)

	roundRect(img, 292, 82, 452, 480, 12, hex(0xffffff), hex(0xd8e4e9), 1)
	circle(img, 338, 126, 28, hex(0x008d7d))
	a.textCenter(img, 338, 137, 22, "AI", hex(0xffffff), true)
	a.text(img, 374, 119, 23, "智药康护 AI 助手", hex(0x142333), true)
	a.text(img, 376, 148, 15, "结合个人档案、体征和药柜库存", hex(0x657586), false)
	a.chip(img, 636, 104, 58, a.aiStatus, hex(0xe7f8f4), hex(0x008d7d))
	line(img, 314, 160, 724, 160, hex(0xe5edf1), 1)
	a.renderChatHistory(img, 310, 168, 416, 312)

	roundRect(img, 310, 494, 416, 54, 14, hex(0xf8fcfc), hex(0xbce5dc), 1)
	pulse := 2 + int(2+2*math.Sin(float64(time.Now().UnixMilli())/260))
	circle(img, 346, 521, 24+pulse, hex(0xd9f3ee))
	circle(img, 346, 521, 24, hex(0x008d7d))
	a.textCenter(img, 346, 531, 21, "麦", hex(0xffffff), true)
	a.text(img, 382, 514, 14, clipText(a.aiVoice, 20), hex(0x657586), false)
	a.text(img, 382, 538, 13, "触摸聊天区上/下半部可翻看历史", hex(0x95a3b2), false)
	roundRect(img, 640, 504, 66, 34, 12, hex(0x008d7d), hex(0x008d7d), 1)
	a.textCenter(img, 673, 527, 16, "发送", hex(0xffffff), true)

	roundRect(img, 762, 82, 242, 480, 12, hex(0xffffff), hex(0xd8e4e9), 1)
	a.text(img, 784, 120, 23, "常见咨询", hex(0x142333), true)
	questions := []string{"头晕血压高怎么办", "今天适合吃哪些药", "药品副作用咨询", "体检指标怎么看", "睡眠不好怎么办"}
	for i, q := range questions {
		y := 146 + i*62
		roundRect(img, 784, y, 190, 46, 10, hex(0xf7fbff), hex(0xcfe1ef), 1)
		a.text(img, 804, y+29, 15, q, hex(0x142333), false)
	}
	roundRect(img, 784, 476, 190, 74, 10, hex(0xfff7f8), hex(0xf6bdc2), 1)
	a.text(img, 800, 506, 14, "胸痛、呼吸困难、意识不清", hex(0xe52f34), false)
	a.text(img, 800, 530, 14, "请立即就医或呼叫急救", hex(0xe52f34), false)
}

func (a *app) renderCamera(img *image.RGBA) {
	a.pageHeader(img, "录入药品", "先扫商品条形码，再识别药盒侧面有效期，确认后自动写入药柜")

	roundRect(img, 20, 82, 610, 430, 12, hex(0xffffff), hex(0xd8e4e9), 1)
	a.text(img, 42, 122, 23, "摄像头画面", hex(0x142333), true)
	fpsText := "等待视频流"
	if a.cameraStreamRunning {
		fpsText = fmt.Sprintf("实时预览 %d fps", a.cameraFPS)
	}
	a.textRight(img, 608, 122, 16, fpsText, hex(0x008d7d), true)
	roundRect(img, 42, 144, 566, 300, 10, hex(0x0b1820), hex(0x0b1820), 1)
	if a.cameraFrame != nil {
		drawImageCover(img, a.cameraFrame, 46, 148, 558, 292)
	} else {
		roundRect(img, 118, 184, 414, 220, 12, hex(0x112b36), hex(0x225e6f), 2)
		a.textCenter(img, 325, 270, 24, "Camera / MJPEG", hex(0x95c7d0), true)
		a.textCenter(img, 325, 306, 16, "正在等待 GStreamer 直连 JPEG 帧", hex(0x95c7d0), false)
		for i := 0; i < 4; i++ {
			line(img, 118+i*138, 184, 118+i*138, 404, hex(0x173b48), 1)
		}
		for i := 0; i < 3; i++ {
			line(img, 118, 184+i*73, 532, 184+i*73, hex(0x173b48), 1)
		}
	}
	scanY := 170 + int(time.Now().UnixMilli()/22)%244
	line(img, 66, scanY, 584, scanY, hex(0x00d2c3), 2)
	line(img, 66, scanY+3, 584, scanY+3, hex(0x65efe3), 1)

	step := firstNonEmpty(a.cameraWorkflowStep, "barcode")
	stepLabels := []string{"1 扫商品条形码", "2 识别有效期", "3 确认录入"}
	stepActive := map[string]int{"barcode": 0, "expiry": 1, "confirm": 2}[step]
	for i, label := range stepLabels {
		x := 42 + i*188
		fill := hex(0xf4f9ff)
		stroke := hex(0xcfe1ef)
		textColor := hex(0x405268)
		if i == stepActive {
			fill = hex(0xe7f8f4)
			stroke = hex(0x00a590)
			textColor = hex(0x008d7d)
		}
		roundRect(img, x, 450, 170, 30, 15, fill, stroke, 1)
		a.textCenter(img, x+85, 471, 14, label, textColor, true)
	}

	roundRect(img, 42, 484, 168, 38, 12, hex(0x008d7d), hex(0x008d7d), 1)
	if step == "barcode" && a.cameraAutoScan {
		a.textCenter(img, 126, 509, 17, "暂停扫条码", hex(0xffffff), true)
	} else if step == "barcode" {
		a.textCenter(img, 126, 509, 17, "开始扫条码", hex(0xffffff), true)
	} else {
		a.textCenter(img, 126, 509, 17, "重扫条码", hex(0xffffff), true)
	}
	roundRect(img, 226, 484, 168, 38, 12, hex(0xf4f9ff), hex(0xadc9ee), 1)
	if step == "expiry" {
		a.textCenter(img, 310, 509, 17, "跳过日期", hex(0x1c66d4), true)
	} else {
		a.textCenter(img, 310, 509, 17, "重新开始", hex(0x1c66d4), true)
	}
	roundRect(img, 410, 484, 198, 38, 12, hex(0xfff8ea), hex(0xf0c781), 1)
	if step == "expiry" {
		a.textCenter(img, 509, 509, 17, "识别有效期", hex(0xd96f00), true)
	} else if a.cameraPendingAdd {
		a.textCenter(img, 509, 509, 17, "录入当前药品", hex(0xd96f00), true)
	} else {
		a.textCenter(img, 509, 509, 17, "等待条码", hex(0xd96f00), true)
	}

	roundRect(img, 650, 82, 354, 430, 12, hex(0xffffff), hex(0xd8e4e9), 1)
	a.text(img, 672, 122, 23, "识别结果", hex(0x142333), true)
	roundRect(img, 672, 150, 284, 42, 10, hex(0xe7f8f4), hex(0xbce5dc), 1)
	a.text(img, 692, 177, 17, a.cameraStatus, hex(0x008d7d), true)
	a.kvColor(img, 672, 226, "药品名称", clipText(a.cameraName, 12), hex(0x142333))
	a.kvColor(img, 672, 270, "商品条码", clipText(a.cameraCode, 14), hex(0x405268))
	a.kvColor(img, 672, 314, "识别信息", clipText(a.cameraMeta, 13), hex(0x405268))
	a.kvColor(img, 672, 358, "有效期", clipText(a.cameraExpire, 12), hex(0xe77800))
	a.kvColor(img, 672, 402, "建议仓位", "自动选择空仓", hex(0x142333))
	for i, line := range wrapRunes(a.cameraNote, 15, 3) {
		a.text(img, 672, 456+i*22, 15, line, hex(0x657586), false)
	}

	roundRect(img, 20, 528, 984, 42, 10, hex(0xe8f5f2), hex(0xe8f5f2), 1)
	a.text(img, 46, 555, 16, "操作：将 69 开头商品条码放进画面中间，保持 10-20cm；识别后再把有效期那一侧对准摄像头。", hex(0x00786f), true)
	if a.cameraPendingAdd {
		a.renderCameraConfirmDialog(img)
	}
}

func (a *app) renderCameraConfirmDialog(img *image.RGBA) {
	fillRectAlpha(img, 0, 0, a.width, a.height, color.RGBA{R: 18, G: 35, B: 48, A: 132})
	roundRect(img, 250, 150, 524, 296, 16, hex(0xffffff), hex(0xbce5dc), 2)
	circle(img, 306, 210, 31, hex(0xe7f8f4))
	a.textCenter(img, 306, 221, 26, "码", hex(0x008d7d), true)
	a.text(img, 356, 198, 26, "确认录入药品", hex(0x142333), true)
	a.text(img, 358, 230, 16, "请核对商品条码、药名和有效期，确认后写入药柜", hex(0x657586), false)
	a.kvColor(img, 286, 282, "药品名称", clipText(firstNonEmpty(a.cameraPendingName, "目录未收录"), 12), hex(0x142333))
	a.kvColor(img, 286, 326, "商品条码", clipText(a.cameraPendingCode, 16), hex(0x405268))
	a.kvColor(img, 286, 370, "有效期", clipText(firstNonEmpty(a.cameraPendingExpire, "待人工确认"), 12), hex(0xe77800))
	roundRect(img, 300, 398, 180, 42, 12, hex(0xf4f9ff), hex(0xadc9ee), 1)
	a.textCenter(img, 390, 425, 18, "取消", hex(0x1c66d4), true)
	roundRect(img, 540, 398, 180, 42, 12, hex(0x008d7d), hex(0x008d7d), 1)
	a.textCenter(img, 630, 425, 18, "录入药柜", hex(0xffffff), true)
}

func (a *app) renderChatHistory(img *image.RGBA, x, y, w, h int) {
	roundRect(img, x, y, w, h, 12, hex(0xfbfeff), hex(0xe5edf1), 1)
	messages := a.aiMessages
	if len(messages) == 0 {
		messages = []aiMessage{{Role: "assistant", Text: "您好，我可以提供用药指导、症状建议和体征解读。", Time: time.Now().Format("15:04")}}
	}
	limit := len(messages) - a.aiScroll
	if limit < 0 {
		limit = 0
	}
	if limit > len(messages) {
		limit = len(messages)
	}
	type bubble struct {
		msg   aiMessage
		lines []string
		w     int
		h     int
	}
	var visible []bubble
	used := 0
	for i := limit - 1; i >= 0; i-- {
		m := messages[i]
		lines := markdownLines(m.Text, 22, 9)
		if m.Role == "user" {
			lines = markdownLines(m.Text, 18, 6)
		}
		bh := max(52, 34+len(lines)*22)
		gap := 12
		if used+bh+gap > h-42 && len(visible) > 0 {
			break
		}
		if m.Role == "user" {
			visible = append(visible, bubble{msg: m, lines: lines, w: a.bubbleWidth(lines, 132, 292) + 34, h: bh})
		} else {
			visible = append(visible, bubble{msg: m, lines: lines, w: a.bubbleWidth(lines, 148, 328) + 36, h: bh})
		}
		used += bh + gap
	}
	if a.aiScroll > 0 {
		a.textCenter(img, x+w/2, y+20, 13, "正在查看历史，向上滑回到最新消息", hex(0x8fa0b2), false)
	}
	yy := y + 26
	for i := len(visible) - 1; i >= 0; i-- {
		b := visible[i]
		if b.msg.Role == "user" {
			a.drawUserBubble(img, x+w-b.w-42, yy, b.w, b.h, b.lines, b.msg.Time)
		} else {
			a.drawAssistantBubble(img, x+18, yy, b.w, b.h, b.lines, b.msg.Time)
		}
		yy += b.h + 12
	}
	if a.aiStatus == "思考中" {
		circle(img, x+32, y+h-28, 15, hex(0x008d7d))
		a.textCenter(img, x+32, y+h-22, 12, "AI", hex(0xffffff), true)
		roundRect(img, x+56, y+h-48, 164, 34, 12, hex(0xffffff), hex(0xcfe1ef), 1)
		a.text(img, x+72, y+h-26, 13, "正在输入", hex(0x657586), false)
		drawTypingDots(img, x+150, y+h-32, time.Now())
	}
	if len(messages) > len(visible) {
		barH := max(32, h*max(1, len(visible))/len(messages))
		trackY := y + 20
		trackH := h - 40
		maxScroll := max(1, len(messages)-max(1, len(visible)))
		scroll := min(maxScroll, max(0, a.aiScroll))
		barY := trackY + (trackH-barH)*(maxScroll-scroll)/maxScroll
		roundRect(img, x+w-10, trackY, 4, trackH, 2, hex(0xe5edf1), hex(0xe5edf1), 1)
		roundRect(img, x+w-11, barY, 6, barH, 3, hex(0x9fb4c6), hex(0x9fb4c6), 1)
	}
}

func (a *app) bubbleWidth(lines []string, minW, maxW int) int {
	w := minW
	for _, line := range lines {
		w = max(w, a.textWidth(15, line)+36)
	}
	return min(maxW, w)
}

func (a *app) drawAssistantBubble(img *image.RGBA, x, y, w, h int, lines []string, t string) {
	circle(img, x+14, y+20, 15, hex(0x008d7d))
	a.textCenter(img, x+14, y+26, 12, "AI", hex(0xffffff), true)
	roundRect(img, x+36, y, w-36, h, 11, hex(0xf7fbff), hex(0xcfe1ef), 1)
	for i, line := range lines {
		a.text(img, x+54, y+28+i*20, 15, line, hex(0x142333), false)
	}
	a.textRight(img, x+w-10, y+h-8, 11, firstNonEmpty(t, "刚刚"), hex(0x8fa0b2), false)
}

func (a *app) drawUserBubble(img *image.RGBA, x, y, w, h int, lines []string, t string) {
	circle(img, x+w-16, y+22, 15, hex(0x1c66d4))
	a.textCenter(img, x+w-16, y+28, 12, "我", hex(0xffffff), true)
	roundRect(img, x, y, w-38, h, 11, hex(0xf1fbf8), hex(0xa9ded2), 1)
	for i, line := range lines {
		a.text(img, x+18, y+28+i*20, 15, line, hex(0x142333), false)
	}
	a.textRight(img, x+w-48, y+h-8, 11, firstNonEmpty(t, "已发送"), hex(0x8fa0b2), false)
}

func (a *app) drawCabinetSlots(img *image.RGBA) {
	layout := cabinetLayout()
	for _, s := range layout {
		a.slotCabinet(img, s)
	}
}

type slotRect struct {
	Slot int
	Kind string
	X, Y int
	W, H int
}

func cabinetLayout() []slotRect {
	var out []slotRect
	slot := 1
	for r := 0; r < 2; r++ {
		for c := 0; c < 4; c++ {
			out = append(out, slotRect{Slot: slot, Kind: "大仓", X: 32 + c*176, Y: 330 + r*116, W: 160, H: 98})
			slot++
		}
	}
	for r := 0; r < 3; r++ {
		for c := 0; c < 2; c++ {
			out = append(out, slotRect{Slot: slot, Kind: "中仓", X: 32 + c*158, Y: 92 + r*76, W: 146, H: 62})
			slot++
		}
	}
	for r := 0; r < 3; r++ {
		for c := 0; c < 3; c++ {
			out = append(out, slotRect{Slot: slot, Kind: "小仓", X: 366 + c*112, Y: 92 + r*76, W: 100, H: 62})
			slot++
		}
	}
	return out
}

func (a *app) slotCabinet(img *image.RGBA, s slotRect) {
	item := a.medBySlot(s.Slot)
	status, bg, fg := stockStatus(item)
	stroke := hex(0x2b2f33)
	if a.selectedSlot == s.Slot {
		stroke = hex(0x008d7d)
	}
	roundRect(img, s.X, s.Y, s.W, s.H, 3, hex(0xffffff), stroke, 2)
	a.text(img, s.X+10, s.Y+25, 22, fmt.Sprintf("%02d", s.Slot), hex(0x000000), true)
	if s.Kind == "大仓" {
		name := s.Kind
		if item != nil {
			name = item.Name
		}
		a.text(img, s.X+10, s.Y+57, 14, clipText(name, 7), hex(0x142333), true)
		roundRect(img, s.X+10, s.Y+s.H-32, 54, 22, 11, bg, bg, 1)
		a.textCenter(img, s.X+37, s.Y+s.H-15, 13, status, fg, true)
		return
	}
	a.text(img, s.X+10, s.Y+49, 13, s.Kind, hex(0x142333), true)
	roundRect(img, s.X+s.W-52, s.Y+8, 42, 20, 10, bg, bg, 1)
	a.textCenter(img, s.X+s.W-31, s.Y+23, 12, status, fg, true)
}

func (a *app) slotSmall(img *image.RGBA, x, y, w, h, slot int, item *medicine) {
	status, _, fg := stockStatus(item)
	roundRect(img, x, y, w, h, 7, hex(0xfbfdfe), hex(0xd8e4e9), 1)
	a.textCenter(img, x+w/2, y+21, 20, fmt.Sprintf("%02d", slot), hex(0x142333), true)
	a.textCenter(img, x+w/2, y+42, 15, status, fg, true)
}

func (a *app) service(img *image.RGBA, x, y, w, h int, fill, fg color.RGBA, title, sub, icon string) {
	roundRect(img, x, y, w, h, 14, fill, hex(0xd8e4e9), 1)
	iconBg := fg
	iconText := fill
	if fill != hex(0x008d7d) {
		iconBg = fg
		iconText = hex(0xffffff)
	}
	circle(img, x+58, y+h/2, 34, iconBg)
	a.drawServiceIcon(img, x+58, y+h/2, icon, iconText, fill)
	a.text(img, x+118, y+52, 29, title, fg, true)
	a.text(img, x+120, y+84, 17, sub, colorFor(fill == hex(0x008d7d), hex(0xdff7f2), hex(0x405268)), false)
	circle(img, x+w-38, y+h/2, 22, hex(0xffffff))
	arrow := fg
	if fill == hex(0x008d7d) {
		arrow = fill
	}
	a.textCenter(img, x+w-38, y+h/2+10, 22, ">", arrow, true)
}

func (a *app) drawServiceIcon(img *image.RGBA, cx, cy int, icon string, fg, bg color.RGBA) {
	switch icon {
	case "药":
		roundRect(img, cx-17, cy-18, 26, 32, 5, fg, fg, 1)
		fillRect(img, cx-12, cy-24, 16, 8, fg)
		line(img, cx-10, cy-2, cx+4, cy-2, bg, 5)
		line(img, cx-3, cy-9, cx-3, cy+6, bg, 5)
		roundRect(img, cx+4, cy+4, 24, 12, 6, bg, bg, 1)
		line(img, cx+8, cy+14, cx+24, cy+4, fg, 3)
	case "测":
		circle(img, cx, cy, 28, hex(0xe8f1ff))
		line(img, cx-25, cy+8, cx-14, cy+8, fg, 4)
		line(img, cx-14, cy+8, cx-6, cy-8, fg, 4)
		line(img, cx-6, cy-8, cx+4, cy+15, fg, 4)
		line(img, cx+4, cy+15, cx+12, cy-2, fg, 4)
		line(img, cx+12, cy-2, cx+28, cy-2, fg, 4)
	case "拍":
		roundRect(img, cx-28, cy-18, 56, 38, 7, fg, fg, 1)
		roundRect(img, cx-14, cy-28, 28, 12, 5, fg, fg, 1)
		circle(img, cx, cy+2, 15, bg)
		circle(img, cx, cy+2, 9, fg)
	default:
		a.textCenter(img, cx, cy+13, 30, icon, fg, true)
	}
}

func (a *app) pageHeader(img *image.RGBA, title, sub string) {
	roundRect(img, 18, 14, 90, 40, 10, hex(0x008d7d), hex(0x008d7d), 1)
	a.textCenter(img, 63, 40, 16, "返回首页", hex(0xffffff), true)
	a.text(img, 130, 38, 30, title, hex(0x142333), true)
	a.text(img, 132, 64, 16, sub, hex(0x657586), false)
	a.renderWifiIndicator(img, 872, 24, 40)
	a.textRight(img, 1002, 64, 16, time.Now().Format("15:04"), hex(0x142333), true)
}

func (a *app) renderWifiIndicator(img *image.RGBA, x, y, w int) {
	connected := a.wifiState == "COMPLETED"
	c := hex(0xe52f34)
	label := "未联网"
	level := 0
	if connected {
		label = "Wi-Fi"
		if a.wifiSSID != "" {
			label = clipText(a.wifiSSID, 8)
		}
		switch {
		case a.wifiSignal >= -75:
			c, level = hex(0x008d7d), 3
		default:
			c, level = hex(0xe52f34), 1
		}
	}
	a.drawWifiIcon(img, x, y+1, c, level)
	if w <= 44 {
		return
	}
	a.text(img, x+28, y+4, 15, label, c, true)
}

func (a *app) drawWifiIcon(img *image.RGBA, cx, cy int, c color.RGBA, level int) {
	dim := hex(0xc8d4dc)
	for i, r := range []int{20, 14, 8} {
		col := dim
		if level >= 3-i {
			col = c
		}
		arc(img, cx, cy+13, r, 215, 325, col, 3)
	}
	circle(img, cx, cy+16, 3, c)
}

func (a *app) sectionLabel(img *image.RGBA, x, y int, s string) {
	a.text(img, x, y, 18, s, hex(0x142333), true)
	line(img, x, y+10, x+206, y+10, hex(0xe5edf1), 1)
}

func (a *app) chip(img *image.RGBA, x, y, w int, text string, bg, fg color.RGBA) {
	roundRect(img, x, y, w, 28, 9, bg, hex(0xd8e4e9), 1)
	a.textCenter(img, x+w/2, y+19, 14, text, fg, true)
}

func (a *app) kvMini(img *image.RGBA, x, y int, k, v string) {
	a.text(img, x, y, 16, k, hex(0x657586), false)
	a.textRight(img, x+204, y, 17, v, hex(0x142333), true)
	line(img, x, y+12, x+204, y+12, hex(0xe5edf1), 1)
}

func (a *app) shield(img *image.RGBA, x, y, w, h int, text string) {
	roundRect(img, x, y, w, h, 12, hex(0x008d7d), hex(0x008d7d), 1)
	a.textCenter(img, x+w/2, y+h/2+11, 24, text, hex(0xffffff), true)
}

func (a *app) kv(img *image.RGBA, x, y int, k, v string) {
	a.kvColor(img, x, y, k, v, hex(0x142333))
}

func (a *app) kvColor(img *image.RGBA, x, y int, k, v string, c color.RGBA) {
	a.text(img, x, y, 17, k, hex(0x657586), false)
	a.textRight(img, 982, y, 17, clipText(v, 10), c, true)
	line(img, x, y+12, 982, y+12, hex(0xd8e4e9), 1)
}

func (a *app) toast(img *image.RGBA, msg string) {
	w := min(680, max(260, 24*len([]rune(msg))))
	x := (a.width - w) / 2
	roundRect(img, x, a.height-76, w, 42, 14, hex(0x142333), hex(0x142333), 1)
	a.textCenter(img, a.width/2, a.height-48, 18, msg, hex(0xffffff), true)
}

func (a *app) medBySlot(slot int) *medicine {
	for i := range a.medicines {
		if a.medicines[i].Slot == slot {
			return &a.medicines[i]
		}
	}
	return nil
}

func (a *app) handleTouch(t touchEvent) {
	a.mu.Lock()
	page := a.page
	a.pressX = t.X
	a.pressY = t.Y
	a.pressUntil = time.Now().Add(180 * time.Millisecond)
	a.mu.Unlock()
	switch page {
	case "cabinet":
		if inside(t, 16, 12, 100, 56) {
			a.setPage("home")
			return
		}
		for _, s := range cabinetLayout() {
			if inside(t, s.X, s.Y, s.W, s.H) {
				a.mu.Lock()
				a.selectedSlot = s.Slot
				a.mu.Unlock()
				return
			}
		}
	case "dispense":
		if inside(t, 18, 14, 100, 50) {
			a.setPage("home")
			return
		}
		a.mu.Lock()
		confirm := a.dispenseConfirm
		a.mu.Unlock()
		if confirm {
			if inside(t, 334, 356, 150, 42) {
				a.mu.Lock()
				a.dispenseConfirm = false
				a.mu.Unlock()
				return
			}
			if inside(t, 548, 356, 150, 42) {
				go a.confirmDispense()
				return
			}
		}
		filters := []string{"全部", "降压", "阿司匹林", "二甲", "低库存"}
		for i, f := range filters {
			if inside(t, 36+i*118, 86, 102, 38) {
				a.mu.Lock()
				a.dispenseFilter = f
				a.dispenseConfirm = false
				filtered := a.filteredMedicines()
				if len(filtered) > 0 {
					a.dispenseSlot = filtered[0].Slot
				}
				a.mu.Unlock()
				return
			}
		}
		filtered := a.filteredMedicines()
		for i, m := range filtered {
			if i >= 6 {
				break
			}
			if inside(t, 48, 198+i*52, 548, 44) {
				a.mu.Lock()
				a.dispenseSlot = m.Slot
				a.dispenseConfirm = false
				a.mu.Unlock()
				return
			}
		}
		for i := 1; i <= 23; i++ {
			col := (i - 1) % 6
			row := (i - 1) / 6
			if inside(t, 668+col*52, 196+row*48, 42, 36) {
				a.mu.Lock()
				a.dispenseSlot = i
				a.dispenseConfirm = false
				a.mu.Unlock()
				return
			}
		}
		if inside(t, 688, 538, 292, 48) {
			a.mu.Lock()
			a.dispenseConfirm = true
			a.mu.Unlock()
			return
		}
	case "camera":
		if inside(t, 18, 14, 100, 50) {
			a.setPage("home")
			return
		}
		a.mu.Lock()
		pending := a.cameraPendingAdd
		step := firstNonEmpty(a.cameraWorkflowStep, "barcode")
		a.mu.Unlock()
		if pending {
			if inside(t, 300, 398, 180, 42) {
				a.dismissPendingMedicine()
				return
			}
			if inside(t, 540, 398, 180, 42) {
				go a.confirmPendingMedicine()
				return
			}
		}
		if inside(t, 42, 484, 168, 38) {
			if step == "barcode" {
				a.toggleCameraAutoScan()
			} else {
				a.clearCameraResult()
			}
			return
		}
		if inside(t, 226, 484, 168, 38) {
			if step == "expiry" {
				a.skipExpiryDate()
			} else {
				a.clearCameraResult()
			}
			return
		}
		if inside(t, 410, 484, 198, 38) {
			if step == "expiry" {
				go a.recognizeExpiryDate()
			} else if pending {
				go a.confirmPendingMedicine()
			} else {
				a.mu.Lock()
				a.message = "请先让摄像头识别商品条形码"
				a.messageUntil = time.Now().Add(1800 * time.Millisecond)
				a.mu.Unlock()
			}
			return
		}
	case "ai":
		if inside(t, 18, 14, 100, 50) {
			a.setPage("home")
			return
		}
		if inside(touchEvent{X: t.StartX, Y: t.StartY}, 310, 168, 416, 312) && abs(t.DY) > 45 && abs(t.DY) > abs(t.DX) {
			a.mu.Lock()
			if t.DY < 0 {
				a.aiScroll = max(0, a.aiScroll-1)
			} else {
				a.aiScroll = min(max(0, len(a.aiMessages)-5), a.aiScroll+1)
			}
			a.mu.Unlock()
			return
		}
		if inside(t, 310, 168, 416, 156) {
			a.mu.Lock()
			a.aiScroll = min(max(0, len(a.aiMessages)-4), a.aiScroll+1)
			a.mu.Unlock()
			return
		}
		if inside(t, 310, 324, 416, 156) {
			a.mu.Lock()
			a.aiScroll = max(0, a.aiScroll-1)
			a.mu.Unlock()
			return
		}
		if inside(t, 310, 494, 70, 54) {
			go a.recordVoice()
			return
		}
		questions := []string{"头晕血压高怎么办", "今天适合吃哪些药", "药品副作用咨询", "体检指标怎么看", "睡眠不好怎么办"}
		for i, q := range questions {
			if inside(t, 772, 146+i*62, 204, 46) {
				go a.askAI(q)
				return
			}
		}
	default:
		if inside(t, 20, 236, 326, 122) {
			next := a.nextPlan()
			a.mu.Lock()
			if next.Slot > 0 {
				a.dispenseSlot = next.Slot
			}
			a.dispenseFilter = "全部"
			a.dispenseConfirm = false
			a.mu.Unlock()
			a.setPage("dispense")
			return
		}
		if inside(t, 360, 236, 310, 122) {
			go a.action("体征已写入档案", func() error {
				return a.api.postForm("/api/vitals/read", url.Values{})
			})
			return
		}
		if inside(t, 686, 236, 318, 122) {
			a.setPage("camera")
			return
		}
		if inside(t, 20, 376, 650, 134) {
			a.setPage("cabinet")
			return
		}
		if inside(t, 686, 376, 318, 92) {
			a.setPage("ai")
			return
		}
	}
}

func (a *app) action(success string, fn func() error) {
	err := fn()
	a.mu.Lock()
	defer a.mu.Unlock()
	if err != nil {
		a.message = "操作失败：" + err.Error()
	} else {
		a.message = success
		a.lastFetch = time.Time{}
	}
	a.messageUntil = time.Now().Add(2500 * time.Millisecond)
}

func (a *app) confirmDispense() {
	a.mu.Lock()
	slot := a.dispenseSlot
	item := a.medBySlot(slot)
	a.dispenseConfirm = false
	if item == nil || item.Stock <= 0 {
		if item == nil {
			a.message = fmt.Sprintf("%02d 仓为空，不能取药", slot)
		} else {
			a.message = fmt.Sprintf("%02d 仓库存不足，不能取药", slot)
		}
		a.messageUntil = time.Now().Add(2500 * time.Millisecond)
		a.mu.Unlock()
		return
	}
	name := item.Name
	a.message = "正在打开 " + name
	a.messageUntil = time.Now().Add(2500 * time.Millisecond)
	a.mu.Unlock()

	err := a.api.postForm("/api/dispense", url.Values{"slot": []string{strconv.Itoa(slot)}})
	a.mu.Lock()
	defer a.mu.Unlock()
	if err != nil {
		a.message = "取药失败：" + err.Error()
	} else {
		a.message = fmt.Sprintf("已触发 %02d 仓：%s", slot, clipText(name, 10))
		a.lastFetch = time.Time{}
	}
	a.messageUntil = time.Now().Add(3000 * time.Millisecond)
}

func (a *app) captureAndRecognize() {
	a.stopCameraStream()
	a.mu.Lock()
	a.cameraStatus = "正在扫码..."
	a.cameraNote = "请将药品条形码或溯源码对准摄像头。"
	a.mu.Unlock()
	defer func() {
		a.mu.Lock()
		onCameraPage := a.page == "camera"
		a.mu.Unlock()
		if onCameraPage {
			go a.startCameraStream()
		}
	}()

	var scan scanMedicineResp
	if err := a.api.postFormJSON("/api/medicine/scan", url.Values{}, &scan); err != nil || !scan.OK {
		a.mu.Lock()
		a.cameraStatus = "扫码失败"
		if err != nil {
			a.cameraNote = err.Error()
		} else {
			a.cameraNote = firstNonEmpty(scan.Error, scan.Detail, "扫码失败")
		}
		a.mu.Unlock()
		return
	}
	a.mu.Lock()
	a.cameraCode = scan.Code
	a.cameraMeta = firstNonEmpty(scan.Scanner, "camera")
	a.cameraNote = scan.Detail
	a.mu.Unlock()

	if !scan.Lookup.Found {
		a.mu.Lock()
		a.cameraStatus = "目录未收录"
		a.cameraName = "待人工核对"
		a.cameraExpire = "待人工确认"
		a.cameraNote = firstNonEmpty(scan.Lookup.Detail, scan.Detail)
		a.mu.Unlock()
		return
	}

	var add autoAddResp
	if err := a.api.postFormJSON("/api/medicine/auto_add", url.Values{"code": []string{scan.Code}, "stock": []string{"1"}}, &add); err != nil || !add.OK {
		a.mu.Lock()
		a.cameraStatus = "识别完成"
		a.cameraName = firstNonEmpty(scan.Lookup.Medicine.Name, "未知药品")
		a.cameraExpire = firstNonEmpty(scan.Lookup.Medicine.ExpireDate, "待确认")
		if err != nil {
			a.cameraNote = "自动录入失败：" + err.Error()
		} else {
			a.cameraNote = firstNonEmpty(add.Error, "自动录入失败，请人工核对后录入")
		}
		a.mu.Unlock()
		return
	}

	a.mu.Lock()
	a.cameraStatus = "已自动录入"
	a.cameraName = firstNonEmpty(add.Medicine.Name, scan.Lookup.Medicine.Name, "未知药品")
	a.cameraExpire = firstNonEmpty(add.Medicine.ExpireDate, scan.Lookup.Medicine.ExpireDate, "待确认")
	a.cameraMeta = fmt.Sprintf("仓位 %02d / %s", add.Slot, firstNonEmpty(scan.Scanner, "scan"))
	a.cameraNote = "已根据溯源码查询药品目录，并写入药柜。请核对药盒实物和有效期。"
	a.message = "扫码完成，药品已录入"
	a.messageUntil = time.Now().Add(2500 * time.Millisecond)
	a.lastFetch = time.Time{}
	a.mu.Unlock()
}

func (a *app) toggleCameraAutoScan() {
	a.mu.Lock()
	defer a.mu.Unlock()
	if firstNonEmpty(a.cameraWorkflowStep, "barcode") != "barcode" {
		a.cameraWorkflowStep = "barcode"
		a.cameraPendingAdd = false
		a.cameraPendingCode = ""
		a.cameraPendingName = ""
		a.cameraPendingExpire = ""
		a.cameraPendingDetail = ""
		a.cameraCode = "待扫描"
		a.cameraExpire = "待识别"
		a.cameraMeta = "商品条形码"
	}
	a.cameraAutoScan = !a.cameraAutoScan
	if a.cameraAutoScan {
		a.cameraStatus = "自动扫条码中"
		a.cameraNote = "请将药盒商品条形码放入画面，识别后进入有效期识别步骤。"
		a.cameraIgnoredCode = ""
	} else {
		a.cameraStatus = "识别已暂停"
		a.cameraNote = "已暂停自动扫条码，点击“开始扫条码”恢复。"
	}
}

func (a *app) clearCameraResult() {
	a.mu.Lock()
	defer a.mu.Unlock()
	a.cameraStatus = "自动扫条码中"
	a.cameraName = "尚未识别"
	a.cameraMeta = "商品条形码"
	a.cameraNote = "已重新开始。第一步：请将药盒商品条形码放入画面。"
	a.cameraCode = "待扫描"
	a.cameraExpire = "待识别"
	a.cameraPendingAdd = false
	a.cameraPendingCode = ""
	a.cameraPendingName = ""
	a.cameraPendingExpire = ""
	a.cameraPendingDetail = ""
	a.cameraIgnoredCode = ""
	a.cameraAutoScan = true
	a.cameraWorkflowStep = "barcode"
}

func (a *app) dismissPendingMedicine() {
	a.mu.Lock()
	defer a.mu.Unlock()
	a.cameraIgnoredCode = a.cameraPendingCode
	a.cameraPendingAdd = false
	a.cameraPendingCode = ""
	a.cameraPendingName = ""
	a.cameraPendingExpire = ""
	a.cameraPendingDetail = ""
	a.cameraAutoScan = true
	a.cameraWorkflowStep = "barcode"
	a.cameraStatus = "继续扫条码中"
	a.cameraNote = "已取消本次录入。移开当前条码或点击重新开始后，可继续识别其他药品。"
}

func (a *app) confirmPendingMedicine() {
	a.mu.Lock()
	code := a.cameraPendingCode
	expire := a.cameraPendingExpire
	if !a.cameraPendingAdd || strings.TrimSpace(code) == "" {
		a.mu.Unlock()
		return
	}
	a.cameraStatus = "正在录入药柜"
	a.cameraNote = "正在根据识别码写入药柜，请稍候。"
	a.mu.Unlock()

	var add autoAddResp
	err := a.api.postFormJSON("/api/medicine/auto_add", url.Values{"code": []string{code}, "stock": []string{"1"}, "expire_date": []string{expire}}, &add)
	a.mu.Lock()
	defer a.mu.Unlock()
	if err != nil || !add.OK {
		a.cameraStatus = "录入失败"
		if err != nil {
			a.cameraNote = err.Error()
		} else {
			a.cameraNote = firstNonEmpty(add.Error, "录入失败，请先补充药品目录")
		}
		return
	}
	a.cameraStatus = "已录入药柜"
	a.cameraName = firstNonEmpty(add.Medicine.Name, a.cameraPendingName, "未知药品")
	a.cameraExpire = firstNonEmpty(add.Medicine.ExpireDate, a.cameraPendingExpire, "待确认")
	a.cameraMeta = fmt.Sprintf("仓位 %02d / 自动识别", add.Slot)
	a.cameraNote = "药品信息已写入药柜。请核对仓位、余量和有效期。"
	a.cameraPendingAdd = false
	a.cameraPendingCode = ""
	a.cameraPendingName = ""
	a.cameraPendingExpire = ""
	a.cameraPendingDetail = ""
	a.cameraAutoScan = true
	a.cameraWorkflowStep = "barcode"
	a.message = "药品已录入药柜"
	a.messageUntil = time.Now().Add(2500 * time.Millisecond)
	a.lastFetch = time.Time{}
}

func (a *app) skipExpiryDate() {
	a.mu.Lock()
	defer a.mu.Unlock()
	if strings.TrimSpace(a.cameraPendingCode) == "" {
		return
	}
	a.cameraWorkflowStep = "confirm"
	a.cameraPendingAdd = true
	a.cameraPendingExpire = firstNonEmpty(a.cameraPendingExpire, "待人工确认")
	a.cameraExpire = a.cameraPendingExpire
	a.cameraStatus = "等待确认录入"
	a.cameraNote = "已跳过有效期 OCR，请在确认前人工核对药盒侧面日期。"
}

func (a *app) recognizeExpiryDate() {
	a.stopCameraStream()
	a.mu.Lock()
	if strings.TrimSpace(a.cameraPendingCode) == "" {
		a.cameraStatus = "请先扫条码"
		a.cameraNote = "第一步需要先识别商品条形码，再识别有效期。"
		a.mu.Unlock()
		return
	}
	a.cameraStatus = "识别有效期中"
	a.cameraNote = "请将药盒侧面有效期/保质期文字面对摄像头，保持清晰。"
	a.mu.Unlock()
	defer func() {
		a.mu.Lock()
		onCameraPage := a.page == "camera"
		a.mu.Unlock()
		if onCameraPage {
			go a.startCameraStream()
		}
	}()

	var resp expiryOCRResp
	err := a.api.postFormJSON("/api/medicine/expiry_ocr", url.Values{}, &resp)
	a.mu.Lock()
	defer a.mu.Unlock()
	if err != nil || !resp.OK {
		a.cameraWorkflowStep = "confirm"
		a.cameraPendingAdd = true
		a.cameraPendingExpire = firstNonEmpty(a.cameraPendingExpire, "待人工确认")
		a.cameraExpire = a.cameraPendingExpire
		if err != nil {
			a.cameraNote = "有效期 OCR 调用失败：" + err.Error()
		} else {
			a.cameraNote = firstNonEmpty(resp.Error, resp.Detail, "有效期 OCR 未返回结果，请人工核对。")
		}
		a.cameraStatus = "等待人工确认"
		return
	}
	a.cameraWorkflowStep = "confirm"
	a.cameraPendingAdd = true
	if resp.Found && strings.TrimSpace(resp.ExpireDate) != "" {
		a.cameraPendingExpire = resp.ExpireDate
		a.cameraExpire = resp.ExpireDate
		a.cameraStatus = "有效期已识别"
		a.cameraNote = firstNonEmpty(resp.Detail, "已识别有效期，请核对后录入药柜。")
	} else {
		a.cameraPendingExpire = firstNonEmpty(a.cameraPendingExpire, "待人工确认")
		a.cameraExpire = a.cameraPendingExpire
		a.cameraStatus = "等待人工确认"
		a.cameraNote = firstNonEmpty(resp.Detail, "未识别到有效期，请在确认前人工核对。")
	}
}

func (a *app) visualRecognizeMedicine() {
	a.stopCameraStream()
	a.mu.Lock()
	a.cameraStatus = "外观识别中"
	a.cameraNote = "正在调用 RKNN 药盒外观识别接口。"
	a.mu.Unlock()
	defer func() {
		a.mu.Lock()
		onCameraPage := a.page == "camera"
		a.mu.Unlock()
		if onCameraPage {
			go a.startCameraStream()
		}
	}()

	var resp visualRecognizeResp
	err := a.api.postFormJSON("/api/medicine/visual_recognize", url.Values{}, &resp)
	a.mu.Lock()
	defer a.mu.Unlock()
	if err != nil {
		a.cameraStatus = "外观识别失败"
		a.cameraNote = err.Error()
		return
	}
	if !resp.OK {
		a.cameraStatus = "外观识别失败"
		a.cameraNote = firstNonEmpty(resp.Error, resp.Detail, "RKNN 外观识别失败")
		return
	}
	if !resp.Found {
		a.cameraStatus = "未识别药盒"
		a.cameraName = "待训练模型"
		a.cameraMeta = firstNonEmpty(resp.Source, "rknn")
		a.cameraNote = firstNonEmpty(resp.Detail, "当前未配置药盒外观识别模型。")
		return
	}
	a.cameraStatus = "外观识别完成"
	a.cameraName = firstNonEmpty(resp.Medicine.Name, "未知药盒")
	a.cameraMeta = fmt.Sprintf("%s / %.0f%%", firstNonEmpty(resp.Source, "rknn"), resp.Medicine.Confidence*100)
	a.cameraNote = "已完成药盒外观识别，请核对后再录入药柜。"
}

func (a *app) askAI(question string) {
	a.mu.Lock()
	a.aiQuestion = question
	a.aiStatus = "思考中"
	a.aiReply = "正在结合档案、体征和药柜库存生成建议..."
	a.aiScroll = 0
	now := time.Now().Format("15:04")
	a.aiMessages = append(a.aiMessages, aiMessage{Role: "user", Text: question, Time: now})
	replyIndex := len(a.aiMessages)
	a.aiMessages = append(a.aiMessages, aiMessage{Role: "assistant", Text: "正在结合档案、体征和药柜库存生成建议...", Time: now})
	a.saveAIHistoryLocked()
	a.mu.Unlock()

	if err := a.streamAI(question, replyIndex); err != nil {
		a.mu.Lock()
		a.aiStatus = "离线"
		a.aiReply = "AI 流式请求失败：" + err.Error()
		if replyIndex < len(a.aiMessages) {
			a.aiMessages[replyIndex].Text = a.aiReply
			a.aiMessages[replyIndex].Time = time.Now().Format("15:04")
			a.saveAIHistoryLocked()
		}
		a.mu.Unlock()
	}
}

func (a *app) streamAI(question string, replyIndex int) error {
	resp, err := a.api.client.PostForm(a.api.base+"/api/ai/chat/stream", url.Values{"message": []string{question}})
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 300 {
		return fmt.Errorf("http %d", resp.StatusCode)
	}
	reader := bufio.NewReader(resp.Body)
	event := ""
	data := ""
	reply := ""
	for {
		line, err := reader.ReadString('\n')
		if err != nil && len(line) == 0 {
			if err == io.EOF {
				break
			}
			return err
		}
		line = strings.TrimRight(line, "\r\n")
		if line == "" {
			if data != "" {
				done := a.applyAIStreamEvent(event, data, replyIndex, &reply)
				if done {
					return nil
				}
			}
			event, data = "", ""
		} else if strings.HasPrefix(line, "event:") {
			event = strings.TrimSpace(strings.TrimPrefix(line, "event:"))
		} else if strings.HasPrefix(line, "data:") {
			if data != "" {
				data += "\n"
			}
			data += strings.TrimSpace(strings.TrimPrefix(line, "data:"))
		}
		if err == io.EOF {
			break
		}
	}
	if strings.TrimSpace(reply) != "" {
		a.finishAIReply(replyIndex, reply)
		go a.speakText(reply)
		return nil
	}
	return nil
}

func (a *app) applyAIStreamEvent(event, raw string, replyIndex int, reply *string) bool {
	var obj map[string]any
	_ = json.Unmarshal([]byte(raw), &obj)
	switch event {
	case "delta":
		if v, ok := obj["delta"].(string); ok && v != "" {
			*reply += v
			a.mu.Lock()
			a.aiStatus = "生成中"
			a.aiReply = *reply
			if replyIndex < len(a.aiMessages) {
				a.aiMessages[replyIndex].Text = *reply
				a.aiMessages[replyIndex].Time = time.Now().Format("15:04")
			}
			a.mu.Unlock()
		}
	case "error":
		msg := "AI 流式响应失败"
		if v, ok := obj["error"].(string); ok && v != "" {
			msg = v
		}
		a.mu.Lock()
		a.aiStatus = "异常"
		a.aiReply = msg
		if replyIndex < len(a.aiMessages) {
			a.aiMessages[replyIndex].Text = msg
			a.aiMessages[replyIndex].Time = time.Now().Format("15:04")
			a.saveAIHistoryLocked()
		}
		a.mu.Unlock()
	case "done":
		a.mu.Lock()
		a.aiStatus = "在线"
		if *reply == "" {
			if v, ok := obj["reply"].(string); ok {
				*reply = v
			}
		}
		if *reply != "" {
			a.aiReply = *reply
			if replyIndex < len(a.aiMessages) {
				a.aiMessages[replyIndex].Text = *reply
				a.aiMessages[replyIndex].Time = time.Now().Format("15:04")
			}
		}
		a.saveAIHistoryLocked()
		a.mu.Unlock()
		if strings.TrimSpace(*reply) != "" {
			go a.speakText(*reply)
		}
		return true
	}
	return false
}

func (a *app) finishAIReply(replyIndex int, reply string) {
	a.mu.Lock()
	defer a.mu.Unlock()
	a.aiStatus = "在线"
	a.aiReply = reply
	if replyIndex < len(a.aiMessages) {
		a.aiMessages[replyIndex].Text = reply
		a.aiMessages[replyIndex].Time = time.Now().Format("15:04")
	}
	a.saveAIHistoryLocked()
}

func (a *app) recordVoice() {
	a.mu.Lock()
	a.aiStatus = "录音中"
	a.aiVoice = "正在录音 3 秒，请对着麦克风说话"
	a.mu.Unlock()

	var resp audioRecordResp
	err := a.api.postFormJSON("/api/audio/record", url.Values{"duration": []string{"3"}}, &resp)
	a.mu.Lock()
	defer a.mu.Unlock()
	if err != nil {
		a.aiStatus = "录音失败"
		a.aiVoice = err.Error()
		return
	}
	if !resp.OK {
		a.aiStatus = "录音失败"
		a.aiVoice = firstNonEmpty(resp.Error, resp.Detail, "麦克风录音失败")
		return
	}
	a.aiStatus = "已录音"
	a.aiVoice = fmt.Sprintf("录音完成 %d 秒，等待接入 Whisper 识别", resp.Duration)
	a.aiMessages = append(a.aiMessages, aiMessage{Role: "user", Text: "已完成一次语音录音，等待接入语音识别。", Time: time.Now().Format("15:04")})
	a.aiScroll = 0
	a.saveAIHistoryLocked()
	a.message = "麦克风录音完成"
	a.messageUntil = time.Now().Add(2500 * time.Millisecond)
}

func (a *app) speakText(text string) {
	text = strings.TrimSpace(text)
	if text == "" {
		return
	}
	a.mu.Lock()
	a.aiVoice = "正在播报 AI 回复..."
	a.mu.Unlock()

	var resp audioSpeakResp
	err := a.api.postFormJSON("/api/audio/speak", url.Values{"text": []string{text}}, &resp)
	a.mu.Lock()
	defer a.mu.Unlock()
	if err != nil {
		a.aiVoice = "播报失败：" + err.Error()
		return
	}
	if !resp.OK {
		a.aiVoice = firstNonEmpty(resp.Error, resp.Detail, "播报失败")
		return
	}
	if resp.Mode == "notice-tone" {
		a.aiVoice = "已验证喇叭播放；需接入中文 TTS 引擎"
	} else {
		a.aiVoice = "AI 回复已播报"
	}
}

func (a *app) setPage(page string) {
	a.mu.Lock()
	old := a.page
	a.page = page
	a.pageChanged = time.Now()
	a.mu.Unlock()
	if page == "camera" {
		go a.startCameraStream()
	} else if old == "camera" {
		a.stopCameraStream()
	}
}

func (a *app) startCameraStream() {
	a.mu.Lock()
	if a.cameraStreamRunning {
		a.mu.Unlock()
		return
	}
	ctx, cancel := context.WithCancel(context.Background())
	a.cameraStreamID++
	streamID := a.cameraStreamID
	a.cameraStreamCancel = cancel
	a.cameraStreamRunning = true
	a.cameraStatus = "实时预览中"
	a.cameraNote = "实时预览中。请先对准商品条形码，识别后再拍药盒侧面有效期。"
	a.mu.Unlock()
	go a.autoScanCameraLoop(ctx)

	defer func() {
		a.mu.Lock()
		if a.cameraStreamID == streamID {
			a.cameraStreamCancel = nil
			a.cameraStreamRunning = false
			a.cameraFPS = 0
			if a.page == "camera" && a.cameraStatus == "实时预览中" {
				a.cameraStatus = "预览已停止"
			}
		}
		a.mu.Unlock()
	}()

	if err := a.streamCameraFromGStreamer(ctx); err != nil && ctx.Err() == nil {
		a.setCameraStreamNote("直连视频流失败，切换到后端备用流：" + err.Error())
		a.streamCameraFromHTTP(ctx)
	}
}

func (a *app) streamCameraFromGStreamer(ctx context.Context) error {
	width := getenv("ZYKH_CAMERA_WIDTH", "424")
	height := getenv("ZYKH_CAMERA_HEIGHT", "240")
	fps := getenv("ZYKH_CAMERA_FPS", "20")
	quality := getenv("ZYKH_CAMERA_QUALITY", "60")
	device := getenv("ZYKH_CAMERA_DEVICE", "/dev/video5")
	args := []string{"-q", "v4l2src", "device=" + device}
	if cameraDeviceIsUVC(device) {
		mjpegCaps := fmt.Sprintf("image/jpeg,width=%s,height=%s,framerate=%s/1", width, height, fps)
		args = append(args, "!", mjpegCaps, "!", "jpegparse", "!", "fdsink", "fd=1", "sync=false")
	} else {
		rawCaps := fmt.Sprintf("video/x-raw,format=NV12,width=%s,height=%s,framerate=%s/1", width, height, fps)
		if gstElementExists("mppjpegenc") {
			args = append(args, "!", rawCaps, "!", "mppjpegenc", "!", "fdsink", "fd=1", "sync=false")
		} else {
			args = append(args, "!", rawCaps, "!", "jpegenc", "quality="+quality, "!", "fdsink", "fd=1", "sync=false")
		}
	}
	cmd := exec.CommandContext(ctx, "gst-launch-1.0", args...)
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return err
	}
	var stderr bytes.Buffer
	cmd.Stderr = &stderr
	if err := cmd.Start(); err != nil {
		return err
	}
	a.setCameraStreamNote(fmt.Sprintf("直连 GStreamer %s %sx%s@%sfps。第一步请对准商品条形码。", filepath.Base(device), width, height, fps))
	frameCount := 0
	tick := time.Now()
	fpsN, err := strconv.Atoi(fps)
	if err != nil || fpsN <= 0 {
		fpsN = 30
	}
	minInterval := time.Second / time.Duration(fpsN)
	lastDecode := time.Time{}
	readErr := readJPEGStream(ctx, stdout, func(frame []byte) {
		now := time.Now()
		if !lastDecode.IsZero() && now.Sub(lastDecode) < minInterval {
			sleepFor := minInterval - now.Sub(lastDecode)
			timer := time.NewTimer(sleepFor)
			select {
			case <-ctx.Done():
				timer.Stop()
				return
			case <-timer.C:
			}
		}
		lastDecode = time.Now()
		img, err := jpeg.Decode(bytes.NewReader(frame))
		if err != nil {
			return
		}
		a.acceptCameraImage(frame, img, &frameCount, &tick)
	})
	waitErr := cmd.Wait()
	if ctx.Err() != nil {
		return nil
	}
	if readErr != nil && readErr != io.EOF {
		return readErr
	}
	if waitErr != nil {
		detail := strings.TrimSpace(stderr.String())
		if detail != "" {
			return fmt.Errorf("%v: %s", waitErr, clipText(detail, 80))
		}
		return waitErr
	}
	return nil
}

func cameraDeviceIsUVC(device string) bool {
	out, err := exec.Command("v4l2-ctl", "-d", device, "--all").CombinedOutput()
	if err != nil {
		return false
	}
	text := strings.ToLower(string(out))
	return strings.Contains(text, "driver name") && strings.Contains(text, "uvcvideo")
}

func gstElementExists(name string) bool {
	if strings.TrimSpace(name) == "" {
		return false
	}
	return exec.Command("gst-inspect-1.0", name).Run() == nil
}

func (a *app) streamCameraFromHTTP(ctx context.Context) {
	streamURL := a.api.base + "/api/camera/stream?width=424&height=240&fps=20&quality=60"
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, streamURL, nil)
	if err != nil {
		a.setCameraStreamError(err)
		return
	}
	client := &http.Client{}
	resp, err := client.Do(req)
	if err != nil {
		if ctx.Err() == nil {
			a.setCameraStreamError(err)
		}
		return
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 300 {
		a.setCameraStreamError(fmt.Errorf("http %d", resp.StatusCode))
		return
	}
	boundary := "zykhframe"
	if _, params, err := mime.ParseMediaType(resp.Header.Get("Content-Type")); err == nil {
		if v := strings.TrimSpace(params["boundary"]); v != "" {
			boundary = strings.TrimPrefix(v, "--")
		}
	}
	reader := multipart.NewReader(resp.Body, boundary)
	frameCount := 0
	tick := time.Now()
	for {
		part, err := reader.NextPart()
		if err != nil {
			if ctx.Err() == nil && err != io.EOF {
				a.setCameraStreamError(err)
			}
			return
		}
		img, err := jpeg.Decode(part)
		_ = part.Close()
		if err != nil {
			continue
		}
		a.acceptCameraImage(nil, img, &frameCount, &tick)
	}
}

func (a *app) acceptCameraImage(jpg []byte, img image.Image, frameCount *int, tick *time.Time) {
	rgba := image.NewRGBA(img.Bounds())
	draw.Draw(rgba, rgba.Bounds(), img, img.Bounds().Min, draw.Src)
	*frameCount = *frameCount + 1
	now := time.Now()
	if !a.mu.TryLock() {
		return
	}
	defer a.mu.Unlock()
	if now.Sub(*tick) >= time.Second {
		elapsed := now.Sub(*tick).Seconds()
		if elapsed > 0 {
			a.cameraFPS = int(float64(*frameCount)/elapsed + 0.5)
		} else {
			a.cameraFPS = *frameCount
		}
		*frameCount = 0
		*tick = now
	}
	a.cameraFrame = rgba
	a.cameraFrameAt = now
	if len(jpg) > 0 {
		a.cameraJPEG = append(a.cameraJPEG[:0], jpg...)
		a.cameraJPEGAt = now
	}
	if a.cameraStatus == "预览已停止" || a.cameraStatus == "实时预览准备中" {
		a.cameraStatus = "实时预览中"
	}
}

func (a *app) autoScanCameraLoop(ctx context.Context) {
	ticker := time.NewTicker(1200 * time.Millisecond)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			a.tryAutoScanFrame()
		}
	}
}

func (a *app) tryAutoScanFrame() {
	a.mu.Lock()
	if a.page != "camera" || firstNonEmpty(a.cameraWorkflowStep, "barcode") != "barcode" || !a.cameraAutoScan || a.cameraScanBusy || a.cameraPendingAdd || time.Since(a.cameraJPEGAt) > 2*time.Second || len(a.cameraJPEG) == 0 {
		a.mu.Unlock()
		return
	}
	if time.Since(a.cameraLastScan) < 1100*time.Millisecond {
		a.mu.Unlock()
		return
	}
	frame := append([]byte(nil), a.cameraJPEG...)
	a.cameraScanBusy = true
	a.cameraLastScan = time.Now()
	a.cameraStatus = "自动扫条码中"
	a.cameraNote = "请将商品条形码保持清晰，识别后会进入有效期识别步骤。"
	a.mu.Unlock()

	go func() {
		defer func() {
			a.mu.Lock()
			a.cameraScanBusy = false
			a.mu.Unlock()
		}()
		code, format, err := a.decodeFrameCode(frame)
		if err != nil || strings.TrimSpace(code) == "" {
			return
		}
		a.onAutoCodeDetected(code, format)
	}()
}

func (a *app) decodeFrameCode(frame []byte) (string, string, error) {
	tmp := filepath.Join(os.TempDir(), "zykh-autoscan.jpg")
	if err := os.WriteFile(tmp, frame, 0600); err != nil {
		return "", "", err
	}
	scanner := getenv("ZYKH_SCAN_CODE", filepath.Join(a.appDir, "bin", "zykh-scan-code"))
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	out, err := exec.CommandContext(ctx, scanner, "-json", tmp).Output()
	if err != nil {
		return "", "", err
	}
	var resp localScanResp
	if err := json.Unmarshal(out, &resp); err != nil {
		return "", "", err
	}
	if !resp.OK {
		return "", "", errors.New(firstNonEmpty(resp.Error, "未识别到码"))
	}
	return strings.TrimSpace(resp.Code), resp.Format, nil
}

func (a *app) onAutoCodeDetected(code, format string) {
	a.mu.Lock()
	if code == a.cameraIgnoredCode {
		a.mu.Unlock()
		return
	}
	a.cameraAutoScan = false
	a.cameraPendingAdd = false
	a.cameraPendingCode = code
	a.cameraPendingName = "目录查询中"
	a.cameraPendingExpire = "待查询"
	a.cameraWorkflowStep = "expiry"
	a.cameraStatus = "条码已识别"
	a.cameraCode = code
	a.cameraMeta = firstNonEmpty(format, "商品条形码")
	a.cameraNote = "已识别商品条形码，正在查询本地药品目录。下一步请将有效期文字面对摄像头。"
	a.mu.Unlock()

	var lookup medicineLookupResp
	err := a.api.getJSON("/api/medicine/lookup?code="+url.QueryEscape(code), &lookup)
	a.mu.Lock()
	defer a.mu.Unlock()
	if err != nil || !lookup.OK {
		a.cameraPendingName = "目录查询失败"
		a.cameraPendingExpire = "待人工确认"
		a.cameraPendingDetail = firstNonEmpty(lookup.Error, "查询失败")
		a.cameraName = "待人工核对"
		a.cameraExpire = "待人工确认"
		a.cameraNote = "商品条码已识别，但本地目录查询失败。可继续识别有效期，确认前需人工核对药名。"
		return
	}
	if !lookup.Found {
		a.cameraPendingName = "目录未收录"
		a.cameraPendingExpire = "待人工确认"
		a.cameraPendingDetail = lookup.Detail
		a.cameraName = "待人工核对"
		a.cameraExpire = "待人工确认"
		a.cameraNote = "商品条码已识别，但本地药品目录未收录。可先识别有效期，之后补充目录再录入。"
		return
	}
	a.cameraPendingName = lookup.Medicine.Name
	a.cameraPendingExpire = lookup.Medicine.ExpireDate
	a.cameraPendingDetail = lookup.Medicine.Dosage
	a.cameraName = lookup.Medicine.Name
	a.cameraExpire = lookup.Medicine.ExpireDate
	if lookup.Source == "showapi" {
		a.cameraMeta = "商品条码 / ShowAPI"
		a.cameraNote = "已联网查询到药品信息并缓存到本地。请将药盒侧面有效期/保质期文字面对摄像头，然后点击识别有效期。"
	} else {
		a.cameraNote = "已根据商品条码查到药品信息。请将药盒侧面有效期/保质期文字面对摄像头，然后点击识别有效期。"
	}
}

func (a *app) stopCameraStream() {
	a.mu.Lock()
	cancel := a.cameraStreamCancel
	a.cameraStreamCancel = nil
	a.cameraStreamRunning = false
	a.cameraFPS = 0
	a.mu.Unlock()
	if cancel != nil {
		cancel()
	}
}

func (a *app) setCameraStreamError(err error) {
	a.mu.Lock()
	defer a.mu.Unlock()
	if a.page != "camera" {
		return
	}
	a.cameraStatus = "预览失败"
	a.cameraNote = "实时画面打开失败：" + err.Error()
}

func (a *app) setCameraStreamNote(note string) {
	a.mu.Lock()
	defer a.mu.Unlock()
	if a.page != "camera" {
		return
	}
	a.cameraStatus = "实时预览中"
	a.cameraNote = note
}

func (a *app) text(img *image.RGBA, x, y, size int, s string, c color.RGBA, bold bool) {
	if bold {
		drawString(img, a.face(size), x, y, s, c)
		drawString(img, a.face(size), x+1, y, s, c)
		return
	}
	drawString(img, a.face(size), x, y, s, c)
}

func (a *app) textCenter(img *image.RGBA, x, y, size int, s string, c color.RGBA, bold bool) {
	w := a.textWidth(size, s)
	a.text(img, x-w/2, y, size, s, c, bold)
}

func (a *app) textRight(img *image.RGBA, x, y, size int, s string, c color.RGBA, bold bool) {
	w := a.textWidth(size, s)
	a.text(img, x-w, y, size, s, c, bold)
}

func (a *app) textWidth(size int, s string) int {
	d := &font.Drawer{Face: a.face(size)}
	return (d.MeasureString(s) + fixed.I(1)).Ceil()
}

func drawString(img *image.RGBA, face font.Face, x, y int, s string, c color.RGBA) {
	d := &font.Drawer{
		Dst:  img,
		Src:  image.NewUniform(c),
		Face: face,
		Dot:  fixed.P(x, y),
	}
	d.DrawString(s)
}

func stockStatus(m *medicine) (string, color.RGBA, color.RGBA) {
	if m == nil || m.Stock <= 0 {
		return "空仓", hex(0xffe8ec), hex(0xe52f34)
	}
	if m.Stock <= 10 {
		return "药量低", hex(0xfff0d5), hex(0xe77800)
	}
	return "正常", hex(0xdff5ec), hex(0x069b5f)
}

func slotKind(slot int) string {
	switch {
	case slot >= 1 && slot <= 8:
		return "大仓"
	case slot >= 9 && slot <= 14:
		return "中仓"
	default:
		return "小仓"
	}
}

func chineseDate(t time.Time) string {
	week := []string{"星期日", "星期一", "星期二", "星期三", "星期四", "星期五", "星期六"}[int(t.Weekday())]
	return fmt.Sprintf("%d月%d日%s", int(t.Month()), t.Day(), week)
}

func inside(t touchEvent, x, y, w, h int) bool {
	return t.X >= x && t.X <= x+w && t.Y >= y && t.Y <= y+h
}

func clipText(s string, n int) string {
	r := []rune(s)
	if len(r) <= n {
		return s
	}
	return string(r[:n]) + "…"
}

func wrapRunes(s string, n, maxLines int) []string {
	r := []rune(strings.TrimSpace(s))
	if len(r) == 0 {
		return []string{""}
	}
	var lines []string
	for len(r) > 0 && len(lines) < maxLines {
		take := min(n, len(r))
		lines = append(lines, string(r[:take]))
		r = r[take:]
	}
	if len(r) > 0 && len(lines) > 0 {
		last := []rune(lines[len(lines)-1])
		if len(last) > 1 {
			lines[len(lines)-1] = string(last[:len(last)-1]) + "…"
		}
	}
	return lines
}

func markdownLines(s string, n, maxLines int) []string {
	var out []string
	for _, line := range strings.Split(strings.TrimSpace(s), "\n") {
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}
		line = strings.TrimLeft(line, "#")
		line = strings.TrimSpace(line)
		line = strings.TrimPrefix(line, "- ")
		line = strings.TrimPrefix(line, "* ")
		line = strings.TrimPrefix(line, "• ")
		line = strings.ReplaceAll(line, "**", "")
		line = strings.ReplaceAll(line, "__", "")
		line = strings.ReplaceAll(line, "`", "")
		if line != "" {
			wrapped := wrapRunes(line, n, max(1, maxLines-len(out)))
			out = append(out, wrapped...)
			if len(out) >= maxLines {
				break
			}
		}
	}
	if len(out) == 0 {
		out = wrapRunes(strings.TrimSpace(s), n, maxLines)
	}
	return out
}

func firstNonEmpty(values ...string) string {
	for _, v := range values {
		if strings.TrimSpace(v) != "" {
			return v
		}
	}
	return ""
}

func getenv(k, fallback string) string {
	v := os.Getenv(k)
	if v == "" {
		return fallback
	}
	return v
}

func getenvInt(k string, fallback int) int {
	v := strings.TrimSpace(os.Getenv(k))
	if v == "" {
		return fallback
	}
	n, err := strconv.Atoi(v)
	if err != nil || n <= 0 {
		return fallback
	}
	return n
}

func hex(v uint32) color.RGBA {
	return color.RGBA{R: uint8(v >> 16), G: uint8(v >> 8), B: uint8(v), A: 255}
}

func colorFor(ok bool, a, b color.RGBA) color.RGBA {
	if ok {
		return a
	}
	return b
}

func fillRect(img *image.RGBA, x, y, w, h int, c color.RGBA) {
	if w <= 0 || h <= 0 {
		return
	}
	rect := image.Rect(x, y, x+w, y+h).Intersect(img.Bounds())
	for yy := rect.Min.Y; yy < rect.Max.Y; yy++ {
		for xx := rect.Min.X; xx < rect.Max.X; xx++ {
			img.SetRGBA(xx, yy, c)
		}
	}
}

func fillRectAlpha(img *image.RGBA, x, y, w, h int, c color.RGBA) {
	if w <= 0 || h <= 0 || c.A == 0 {
		return
	}
	rect := image.Rect(x, y, x+w, y+h).Intersect(img.Bounds())
	alpha := int(c.A)
	inv := 255 - alpha
	for yy := rect.Min.Y; yy < rect.Max.Y; yy++ {
		for xx := rect.Min.X; xx < rect.Max.X; xx++ {
			i := img.PixOffset(xx, yy)
			img.Pix[i+0] = uint8((int(c.R)*alpha + int(img.Pix[i+0])*inv) / 255)
			img.Pix[i+1] = uint8((int(c.G)*alpha + int(img.Pix[i+1])*inv) / 255)
			img.Pix[i+2] = uint8((int(c.B)*alpha + int(img.Pix[i+2])*inv) / 255)
			img.Pix[i+3] = 255
		}
	}
}

func roundRect(img *image.RGBA, x, y, w, h, r int, fill, stroke color.RGBA, sw int) {
	fillRoundRect(img, x, y, w, h, r, stroke)
	fillRoundRect(img, x+sw, y+sw, w-2*sw, h-2*sw, max(0, r-sw), fill)
}

func fillRoundRect(img *image.RGBA, x, y, w, h, r int, c color.RGBA) {
	if r <= 0 {
		fillRect(img, x, y, w, h, c)
		return
	}
	fillRect(img, x+r, y, w-2*r, h, c)
	fillRect(img, x, y+r, w, h-2*r, c)
	corners := [][2]int{{x + r, y + r}, {x + w - r - 1, y + r}, {x + r, y + h - r - 1}, {x + w - r - 1, y + h - r - 1}}
	for yy := -r; yy <= r; yy++ {
		for xx := -r; xx <= r; xx++ {
			if xx*xx+yy*yy > r*r {
				continue
			}
			for i, center := range corners {
				if (i == 0 && (xx > 0 || yy > 0)) || (i == 1 && (xx < 0 || yy > 0)) ||
					(i == 2 && (xx > 0 || yy < 0)) || (i == 3 && (xx < 0 || yy < 0)) {
					continue
				}
				set(img, center[0]+xx, center[1]+yy, c)
			}
		}
	}
}

func circle(img *image.RGBA, cx, cy, r int, c color.RGBA) {
	for y := -r; y <= r; y++ {
		for x := -r; x <= r; x++ {
			if x*x+y*y <= r*r {
				set(img, cx+x, cy+y, c)
			}
		}
	}
}

func circleAlpha(img *image.RGBA, cx, cy, r int, c color.RGBA) {
	if r <= 0 || c.A == 0 {
		return
	}
	alpha := int(c.A)
	inv := 255 - alpha
	for y := -r; y <= r; y++ {
		for x := -r; x <= r; x++ {
			if x*x+y*y > r*r {
				continue
			}
			px := cx + x
			py := cy + y
			if !image.Pt(px, py).In(img.Bounds()) {
				continue
			}
			i := img.PixOffset(px, py)
			img.Pix[i+0] = uint8((int(c.R)*alpha + int(img.Pix[i+0])*inv) / 255)
			img.Pix[i+1] = uint8((int(c.G)*alpha + int(img.Pix[i+1])*inv) / 255)
			img.Pix[i+2] = uint8((int(c.B)*alpha + int(img.Pix[i+2])*inv) / 255)
			img.Pix[i+3] = 255
		}
	}
}

func line(img *image.RGBA, x1, y1, x2, y2 int, c color.RGBA, width int) {
	if x1 == x2 {
		fillRect(img, x1-width/2, min(y1, y2), width, abs(y2-y1)+1, c)
		return
	}
	if y1 == y2 {
		fillRect(img, min(x1, x2), y1-width/2, abs(x2-x1)+1, width, c)
	}
}

func arc(img *image.RGBA, cx, cy, r, startDeg, endDeg int, c color.RGBA, width int) {
	for d := startDeg; d <= endDeg; d += 2 {
		rad := float64(d) * math.Pi / 180
		x := cx + int(math.Cos(rad)*float64(r))
		y := cy + int(math.Sin(rad)*float64(r))
		circle(img, x, y, max(1, width/2), c)
	}
}

func set(img *image.RGBA, x, y int, c color.RGBA) {
	if image.Pt(x, y).In(img.Bounds()) {
		img.SetRGBA(x, y, c)
	}
}

func drawImageCover(dst *image.RGBA, src *image.RGBA, x, y, w, h int) {
	if src == nil || w <= 0 || h <= 0 {
		return
	}
	sb := src.Bounds()
	sw, sh := sb.Dx(), sb.Dy()
	if sw <= 0 || sh <= 0 {
		return
	}
	scaleW := float64(w) / float64(sw)
	scaleH := float64(h) / float64(sh)
	scale := scaleW
	if scaleH > scale {
		scale = scaleH
	}
	drawW := int(float64(sw) * scale)
	drawH := int(float64(sh) * scale)
	offsetX := (drawW - w) / 2
	offsetY := (drawH - h) / 2
	rect := image.Rect(x, y, x+w, y+h).Intersect(dst.Bounds())
	invScale := int((1 << 16) / scale)
	startY := (rect.Min.Y - y + offsetY) * invScale
	startX := (rect.Min.X - x + offsetX) * invScale
	for yy := rect.Min.Y; yy < rect.Max.Y; yy++ {
		sy := sb.Min.Y + min(sh-1, max(0, startY>>16))
		sxFixed := startX
		for xx := rect.Min.X; xx < rect.Max.X; xx++ {
			sx := sb.Min.X + min(sw-1, max(0, sxFixed>>16))
			dst.SetRGBA(xx, yy, src.RGBAAt(sx, sy))
			sxFixed += invScale
		}
		startY += invScale
	}
}

func readJPEGStream(ctx context.Context, r io.Reader, onFrame func([]byte)) error {
	buf := make([]byte, 32*1024)
	pending := make([]byte, 0, 256*1024)
	inFrame := false
	for {
		n, err := r.Read(buf)
		if n > 0 {
			data := buf[:n]
			for len(data) > 0 {
				if !inFrame {
					i := indexSOI(data)
					if i < 0 {
						break
					}
					data = data[i:]
					pending = pending[:0]
					inFrame = true
				}
				pending = append(pending, data...)
				if j := indexEOI(pending); j >= 0 {
					frame := append([]byte(nil), pending[:j+2]...)
					onFrame(frame)
					rest := append([]byte(nil), pending[j+2:]...)
					pending = pending[:0]
					inFrame = false
					data = rest
					if len(pending) > 512*1024 {
						pending = pending[:0]
						inFrame = false
					}
					continue
				}
				if len(pending) > 1024*1024 {
					pending = pending[:0]
					inFrame = false
				}
				break
			}
		}
		if err != nil {
			if ctx.Err() != nil {
				return nil
			}
			return err
		}
	}
}

func indexSOI(b []byte) int {
	for i := 0; i+1 < len(b); i++ {
		if b[i] == 0xff && b[i+1] == 0xd8 {
			return i
		}
	}
	return -1
}

func indexEOI(b []byte) int {
	for i := 0; i+1 < len(b); i++ {
		if b[i] == 0xff && b[i+1] == 0xd9 {
			return i
		}
	}
	return -1
}

func drawTypingDots(img *image.RGBA, x, y int, now time.Time) {
	phase := int(now.UnixMilli()/220) % 3
	for i := 0; i < 3; i++ {
		r := 4
		c := hex(0x9fb4c6)
		if i == phase {
			r = 6
			c = hex(0x008d7d)
		}
		circle(img, x+i*18, y, r, c)
	}
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}

func max(a, b int) int {
	if a > b {
		return a
	}
	return b
}

func abs(a int) int {
	if a < 0 {
		return -a
	}
	return a
}

func main() {
	time.Local = time.FixedZone("Asia/Shanghai", 8*60*60)
	appDir := getenv("ZYKH_APP_DIR", "/userdata/zykh_app")
	width := getenvInt("ZYKH_UI_WIDTH", defaultWidth)
	height := getenvInt("ZYKH_UI_HEIGHT", defaultHeight)
	fbPath := getenv("ZYKH_FB", "/dev/fb0")
	drmPath := getenv("ZYKH_DRM_CARD", "/dev/dri/card0")
	renderTarget := strings.ToLower(getenv("ZYKH_RENDER_TARGET", "fb"))
	touchPath := getenv("ZYKH_TOUCH_EVENT", defaultTouchDev)
	apiBase := getenv("ZYKH_API_BASE", "http://127.0.0.1:8080")

	var sink renderSink
	var err error
	switch renderTarget {
	case "wayland", "wl":
		sink, err = openWaylandSink(width, height)
		if err != nil {
			fatal("open wayland", err)
		}
	case "drm", "kms":
		sink, err = openDRMSink(drmPath, width, height)
		if err != nil {
			fatal("open drm", err)
		}
	default:
		sink, err = openFramebuffer(fbPath, width, height)
		if err != nil {
			fatal("open framebuffer", err)
		}
	}
	defer sink.Close()
	width, height = sink.Size()

	ui, err := newApp(width, height, appDir, newAPI(apiBase))
	if err != nil {
		fatal("init ui", err)
	}
	if ui.page == "camera" {
		go ui.startCameraStream()
	}

	touches := make(chan touchEvent, 8)
	startTouchReader(touchPath, width, height, touches)

	renderAndBlit := newRenderLoopLogger(ui, sink)
	renderAndBlit()
	for {
		timer := time.NewTimer(ui.frameInterval())
		select {
		case t := <-touches:
			timer.Stop()
			ui.handleTouch(t)
			renderAndBlit()
		case <-timer.C:
			renderAndBlit()
		}
	}
}

func (a *app) frameInterval() time.Duration {
	a.mu.Lock()
	defer a.mu.Unlock()
	now := time.Now()
	if now.Sub(a.pageChanged) < 280*time.Millisecond || now.Before(a.pressUntil) || now.Before(a.messageUntil) {
		return 33 * time.Millisecond
	}
	switch a.page {
	case "camera":
		return 33 * time.Millisecond
	case "ai":
		return 66 * time.Millisecond
	default:
		return 100 * time.Millisecond
	}
}

func (a *app) currentPage() string {
	a.mu.Lock()
	defer a.mu.Unlock()
	return a.page
}

func newRenderLoopLogger(ui *app, sink renderSink) func() {
	var frames int
	var total time.Duration
	last := time.Now()
	return func() {
		start := time.Now()
		sink.Blit(ui.render())
		cost := time.Since(start)
		frames++
		total += cost
		now := time.Now()
		if now.Sub(last) >= time.Second {
			avg := 0.0
			if frames > 0 {
				avg = float64(total.Microseconds()) / float64(frames) / 1000.0
			}
			fmt.Fprintf(os.Stderr, "render_fps=%d render_avg_ms=%.1f page=%s\n", frames, avg, ui.currentPage())
			frames = 0
			total = 0
			last = now
		}
	}
}

func fatal(step string, err error) {
	if err == nil {
		err = errors.New("unknown error")
	}
	var buf bytes.Buffer
	_, _ = fmt.Fprintf(&buf, "zykh-go-ui: %s failed: %v\n", step, err)
	_, _ = os.Stderr.Write(buf.Bytes())
	os.Exit(1)
}
