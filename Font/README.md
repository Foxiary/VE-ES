# Font/

Font nguồn để render `.ffu`. Thư mục này **gitignored** (37 MB, đa số biến thể
không dùng) — tải lại từ Google Fonts khi cần.

Cả ba đều **SIL Open Font License**, nên phân phối kèm bản dịch được, miễn giữ
file `OFL.txt` đi kèm.

| font | dùng cho | lý do |
|---|---|---|
| [Newsreader](https://fonts.google.com/specimen/Newsreader) | advfont1, sysfont | serif, khớp mincho |
| [Source Serif 4](https://fonts.google.com/specimen/Source+Serif+4) | advfont2 | serif nhẹ hơn |
| [Cabin](https://fonts.google.com/specimen/Cabin) | advfont3, advfont4 | sans, khớp gothic |

Giải nén nguyên bộ vào đây, giữ đúng tên thư mục:

```
Font/Newsreader/static/...
Font/Source_Serif_4/static/...
Font/Cabin/static/...
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
