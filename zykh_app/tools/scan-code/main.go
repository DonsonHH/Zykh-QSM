package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"image"
	_ "image/jpeg"
	_ "image/png"
	"os"
	"strings"

	"github.com/makiuchi-d/gozxing"
	"github.com/makiuchi-d/gozxing/aztec"
	"github.com/makiuchi-d/gozxing/datamatrix"
	"github.com/makiuchi-d/gozxing/oned"
	"github.com/makiuchi-d/gozxing/qrcode"
)

type output struct {
	OK     bool   `json:"ok"`
	Code   string `json:"code,omitempty"`
	Format string `json:"format,omitempty"`
	Error  string `json:"error,omitempty"`
}

func main() {
	jsonOut := flag.Bool("json", false, "print JSON")
	flag.Parse()
	if flag.NArg() != 1 {
		write(*jsonOut, output{OK: false, Error: "usage: zykh-scan-code [-json] image.jpg"})
		os.Exit(2)
	}

	code, format, err := decodeFile(flag.Arg(0))
	if err != nil {
		write(*jsonOut, output{OK: false, Error: err.Error()})
		os.Exit(1)
	}
	write(*jsonOut, output{OK: true, Code: strings.TrimSpace(code), Format: format})
}

func decodeFile(path string) (string, string, error) {
	f, err := os.Open(path)
	if err != nil {
		return "", "", err
	}
	defer f.Close()

	img, _, err := image.Decode(f)
	if err != nil {
		return "", "", err
	}
	bmp, err := gozxing.NewBinaryBitmapFromImage(img)
	if err != nil {
		return "", "", err
	}
	hints := map[gozxing.DecodeHintType]interface{}{
		gozxing.DecodeHintType_TRY_HARDER:    true,
		gozxing.DecodeHintType_CHARACTER_SET: "UTF-8",
		gozxing.DecodeHintType_POSSIBLE_FORMATS: []gozxing.BarcodeFormat{
			gozxing.BarcodeFormat_QR_CODE,
			gozxing.BarcodeFormat_DATA_MATRIX,
			gozxing.BarcodeFormat_AZTEC,
			gozxing.BarcodeFormat_EAN_13,
			gozxing.BarcodeFormat_EAN_8,
			gozxing.BarcodeFormat_UPC_A,
			gozxing.BarcodeFormat_UPC_E,
			gozxing.BarcodeFormat_CODE_128,
			gozxing.BarcodeFormat_CODE_39,
			gozxing.BarcodeFormat_CODE_93,
			gozxing.BarcodeFormat_ITF,
		},
	}
	readers := []gozxing.Reader{
		qrcode.NewQRCodeReader(),
		datamatrix.NewDataMatrixReader(),
		aztec.NewAztecReader(),
		oned.NewEAN13Reader(),
		oned.NewEAN8Reader(),
		oned.NewUPCAReader(),
		oned.NewUPCEReader(),
		oned.NewCode128Reader(),
		oned.NewCode39Reader(),
		oned.NewCode93Reader(),
		oned.NewITFReader(),
	}
	var lastErr error
	for _, reader := range readers {
		result, err := reader.Decode(bmp, hints)
		if err == nil {
			return result.GetText(), result.GetBarcodeFormat().String(), nil
		}
		lastErr = err
	}
	return "", "", lastErr
}

func write(asJSON bool, out output) {
	if asJSON {
		_ = json.NewEncoder(os.Stdout).Encode(out)
		return
	}
	if out.OK {
		fmt.Printf("%s\t%s\n", out.Code, out.Format)
		return
	}
	fmt.Fprintln(os.Stderr, out.Error)
}
