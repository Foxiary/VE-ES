# Font/

Font nguồn để render `.ffu`. Thư mục này **gitignored** (~29 MB) — tải lại từ
Google Fonts khi cần.

Source Serif 4, Newsreader và Open Sans là **SIL Open Font License**, Tinos là
**Apache 2.0** — cả bốn phân phối kèm bản dịch được, miễn giữ file giấy phép đi
kèm (`OFL.txt` / `LICENSE.txt`).

| font | dùng cho | lý do |
|---|---|---|
| [Newsreader](https://fonts.google.com/specimen/Newsreader) | sysfont | serif, khớp mincho |
| [Tinos](https://fonts.google.com/specimen/Tinos) | advfont1 | bản EN dùng Jomolhari (chỉ 48/146 ký tự Việt); Tinos cùng cụm Times |
| [Source Serif 4](https://fonts.google.com/specimen/Source+Serif+4) | advfont2 | đúng font gốc của bản EN |
| [Open Sans](https://fonts.google.com/specimen/Open+Sans) | advfont3 (SemiBold), advfont4 (Regular) | advfont3 đúng font gốc; advfont4 thay Sawarabi Gothic (120/146) cho cùng họ |

Giải nén vào đây, giữ đúng tên thư mục:

```
Font/Newsreader/static/Newsreader_24pt-Regular.ttf
Font/Tinos/Tinos-Regular.ttf
Font/Source_Serif_4/SourceSerif4-VariableFont_opsz,wght.ttf
Font/Open_Sans/OpenSans-SemiBold.ttf
Font/Open_Sans/OpenSans-Regular.ttf
```

File cụ thể dùng cho từng `.ffu` khai trong `../fonts.json`.

## Chọn font thay thế

Bắt buộc **đủ 146 ký tự tiếng Việt có dấu**. Kiểm nhanh:

```python
from fontTools.ttLib import TTFont
VN = "AÀÁẢÃẠĂẰẮẲẴẶÂẦẤẨẪẬEÈÉẺẼẸÊỀẾỂỄỆIÌÍỈĨỊOÒÓỎÕỌÔỒỐỔỖỘƠỜỚỞỠỢUÙÚỦŨỤƯỪỨỬỮỰYỲÝỶỸỴĐ"
VN = [c for ch in VN for c in (ch, ch.lower())]
cm = set(TTFont('font.ttf', lazy=True).getBestCmap())
print(sum(1 for c in VN if ord(c) in cm), '/ 146')
```

Nên khớp kiểu chữ gốc: advfont1/2 và sysfont là mincho (dùng serif), advfont3/4
là gothic (dùng sans). Dùng cùng một font cho cả bốn sẽ làm tuỳ chọn
Options → Display → Font mất hết ý nghĩa.

Không cần font có kanji: ký tự nào font thiếu thì `ffugen.py` giữ nguyên bitmap
gốc từ template. Đã quét 341 font hệ thống Windows — **không cái nào** vừa đủ
tiếng Việt vừa có kanji, nên đây là đường mặc định chứ không phải ngoại lệ.
