# tools/

Thư viện + script cho bản dịch Virche. Chi tiết format nằm ở `../CLAUDE.md`.

Không tool nào phụ thuộc vào Virche: đưa `.ffu` / `.cpk` của game Otomate khác
vào là chạy. Thứ duy nhất gắn với game này là `translate_glossary.py`.

## Tool chính

### `ffugen.py` — sinh `.ffu` từ OTF/TTF

```bash
python ffugen.py --template stock.ffu --out new.ffu --font "path/to.ttf"
python ffugen.py --template stock.ffu --out new.ffu \
    --font "latin.ttf" --font "cjk.otf#0"        # chuỗi fallback
```

Cỡ chữ **tự dò** cho khớp chiều cao chữ hoa của template — đừng chỉ định `--px`
trừ khi có lý do, vì kanji giữ từ template nên Latin lệch cỡ là lộ ngay.

`--font` lặp được nhiều lần theo thứ tự ưu tiên. Ký tự không font nào có sẽ
**giữ nguyên bitmap gốc** từ template, nên dùng font chỉ có Latin vẫn được:
kanji giữ hình gốc của game.

Tham số hay dùng: `--pad` (đệm trên/dưới, tăng nếu dấu sát mép), `--match-char`
(ký tự dùng để dò cỡ, mặc định `A`), `--no-vn` (không thêm charset tiếng Việt).

### `cpk.py` — bung / đóng gói `.cpk`

```bash
python cpk.py list   SYSTEM.cpk
python cpk.py unpack SYSTEM.cpk font out_dir      # lọc theo chuỗi trong đường dẫn
python cpk.py repack SYSTEM.cpk SYSTEM_vn.cpk replacement_dir
```

Khi repack, file trùng tên trong `replacement_dir` được thay và ghi **không
nén**; file khác chép nguyên dạng đã nén.

### `gbnl.py` — đọc / dựng lại `.gbin` và `.gstr`

```bash
python gbnl.py file.gbin      # in schema + kiểm tra round-trip
```

Dùng cái này khi chuỗi tiếng Việt **dài hơn** bản gốc — nó dựng lại string pool
và ánh xạ lại toàn bộ offset. Chạy không tham số sẽ báo round-trip có
`BIT-IDENTICAL` không; **luôn kiểm tra trước khi tin tool**.

### `mksheet.py` — rút toàn bộ text trong game ra `.xlsx`

```bash
python mksheet.py --out sheet.xlsx                       # đọc thẳng STORY.cpk + SYSTEM.cpk
python mksheet.py --story work/story-us --out sheet.xlsx # hoặc thư mục đã bung
python mksheet.py --story STORY.cpk --no-system --no-jp --out story.xlsx
```

Mỗi file kịch bản thành một sheet (`100`, `101`, …), mỗi file trong `DATABASE/`
thành một sheet tên chữ (`strSystem`, `dbDictionary`, …). Cột:
`ID | Nguồn (EN) | Tiếng Việt | Tiếng Nhật | Ghi chú | kind | bytes`. Sheet
`_README` đầu workbook là hướng dẫn cho người dịch. Trên bản tiếng Anh
`01009CF01BAC4000` ra **97.110 dòng**, trong đó **99,9%** có đối chiếu tiếng
Nhật.

**Thứ tự cột không được đổi.** `checksheet.rows_of()` đọc cột nguồn ở B và cột
dịch ở C **theo vị trí**, mà `applystory.py` lẫn `portjp2us.py` đều đi qua hàm
đó. Vì vậy cột tiếng Nhật nằm ở **D**, sau cột dịch, chứ không nằm cạnh cột
nguồn cho dễ đọc: chèn nó vào C thì cả ba tool sẽ coi tiếng Nhật là bản dịch và
ghi thẳng vào game. Từ cột D trở đi các tool bỏ qua, nên thêm cột ghi chú thoải
mái.

Chỉ lấy text người chơi thực sự đọc được. Kịch bản phần lớn là tên asset và tên
cờ, nên tool lọc theo **opcode** chứ không quét mọi block giải mã được UTF-8:

| kind | nội dung |
|---|---|
| `text` | một dòng trong khung thoại |
| `name` | tên người nói |
| `choice` | một lựa chọn trong menu |
| `title` | tên chương, dạng `<khóa tiếng Nhật>@<chữ hiện ra>` |
| `var` | khung thoại game lưu sẵn nhiều bản (thay tên / đổi màu chữ) |
| `ui` | text giao diện và từ điển trong `SYSTEM.cpk` |

`opcode` là **con trỏ vào GLOBAL_DATA** nên giá trị đổi theo layout từng file.
Tool dò opcode `text` bằng nội dung (opcode chứa nhiều văn xuôi nhất) rồi dời cả
bảng theo đúng độ lệch đó — bản tiếng Anh lệch 0 ở 49 file và 16 ở 5 file, bản
tiếng Nhật lệch 32. File nào dò ra độ lệch mà opcode `name` không tồn tại thì bị
**bỏ qua và báo ra**, không đoán bừa.

Cột `bytes` là độ dài câu gốc tính theo byte UTF-8. Bản gốc không có block nào
quá **84 byte** và block 98 byte làm treo game, nên đây là hạn mức cho câu dịch —
chữ Việt có dấu tốn 2 byte mỗi chữ. Hạn mức này chỉ áp cho sheet kịch bản; sheet
`ui` đi qua `gbnl.py` nên dài bao nhiêu cũng được.

Cột string của `.gbin` / `.gstr` trộn lẫn text hiển thị với khóa nội bộ mà không
có phép thử nội dung nào tách được (`YES` là text, `sure1` là cờ, nhìn giống
nhau), nên `DB_COLUMNS` trong file liệt kê tay từng cột theo schema. Cột không
có trong bảng bị bỏ qua **và in ra màn hình**.

#### Cột tiếng Nhật

Lấy từ `--jp-story` / `--jp-system` (mặc định `work/jp/CONTENTS/`); không có thì
tool báo một dòng rồi bỏ cột, `--no-jp` để tắt hẳn.

Hai bản không khớp được theo nội dung — cùng một câu viết khác nhau ở mỗi thứ
tiếng — nên ghép **theo cấu trúc**, đúng cách `portjp2us.py` đang dùng để chuyển
bản dịch. Hai build biên dịch từ cùng một nguồn: 50/54 file kịch bản trùng số
lệnh, 4 file lệch 1–3 lệnh thì difflib căn lại theo chữ ký `(số param, số
block)`. Bảng opcode tiếng Nhật suy ra từ chỗ các lệnh `text` tiếng Anh rơi vào,
**không** dò bằng nội dung (`detect_delta` tìm chữ thường ASCII, tiếng Nhật
không có). Ô chỉ được điền khi lệnh bên Nhật cùng `kind`, nên căn lệch thì ô
trống chứ không ghép nhầm câu của người khác.

Đo trên bản tiếng Anh: **82.685/82.685** lệnh `text` rơi đúng vào một lệnh
`text` tiếng Nhật, và **99,9%** dòng `name` khớp cùng một tên tiếng Nhật.

> Bản tiếng Anh có ngắt dòng lại, nên dòng N của hai bản là **cùng một dòng trên
> màn hình**, chưa chắc cùng một câu. Đọc cột tiếng Nhật như ngữ cảnh của khung
> thoại, đừng coi là bản dịch sát từng chữ.

**Database không cùng thứ tự bản ghi.** `dbDictionary` sắp theo alphabet của
từng thứ tiếng, nên bản ghi số 2 là `Allelopathy` bên Anh nhưng `アルペシェール`
bên Nhật — ghép theo chỉ số sẽ gán nhầm từ cho **93/98** mục. `db_pairing()` vì
vậy phải **chứng minh** thứ tự trước khi dùng: hoặc hai bảng bản ghi giống hệt
nhau sau khi che các ô chuỗi, hoặc tìm được một cột duy nhất ở cả hai bên và
mang cùng tập giá trị để làm khóa. `dbDictionary` ghép theo id số của từ, các
file còn lại ghép theo chỉ số. Không thỏa cái nào thì để trống, không đoán.

### `applyen.py` — ghi bản dịch vào bản ENG theo cột `EN ID`

```bash
python applyen.py sheet.xlsx work/story-us out_dir --dry-run
python applyen.py sheet.xlsx work/story-us out_dir --max-bytes 84 --report qua-dai.csv
```

Dùng cái này khi bảng dịch **có cột `EN ID`**, vì đó là toạ độ chính xác chứ
không phải gợi ý: đo trên cả 54 sheet, **95.355** `EN ID` trỏ đúng block có nội
dung khớp nguyên văn cột D, **0** trỏ sai. Nhờ vậy bỏ được toàn bộ khâu dò nội
dung, gỡ trùng lặp và dóng cấu trúc mà hai tool kia phải làm.

Cột: `A ID | B Japanese | C Tiếng Việt | D English | E EN ID | F EN Note`.
Tiêu đề cột B ghi "English" nhưng nội dung là tiếng Nhật — sai từ bảng gốc.

Offset chỉ được tin **sau khi** nội dung block khớp đúng cột D; lệch thì bỏ
dòng và đếm, không ghi liều. Markup (`#NAME`…) cũng phải khớp block bị đè.

Kết quả trên bản `01009CF01BAC4000`: **94.497/102.809** dòng đã dịch được ghi
(91,9%). Bỏ qua: 7.208 dòng chỉ có bên Nhật nên build ENG không có, 3.153 chưa
dịch, 851 lệch markup, 253 thiếu `EN ID`.

`--max-bytes 84` dựng bản dè dặt, bỏ 1.305 câu vượt trần (xem mục dưới).

### Bộ tool kịch bản đi kèm

- `stcm2l.py` — đọc / dựng lại `.DAT` (STCM2L); chạy trực tiếp để tự kiểm tra file
- `checksheet.py` — đối chiếu bảng dịch với `.DAT`, xem bảng có đúng build không
- `applyen.py` — ghi bản dịch vào bản ENG theo `EN ID` (**ưu tiên dùng**)
- `applystory.py` — ghi bản dịch, khớp theo nội dung, khi bảng không có `EN ID`
- `portjp2us.py` — chuyển bản dịch neo theo bản Nhật sang build khác

Quy trình: `mksheet.py` → dịch cột C → `checksheet.py` → `applyen.py` →
`cpk.py repack`.

### Trần 84 byte cho một block

Bản Nhật và bản Anh biên dịch độc lập, **cả hai đều không có block text nào quá
84 byte** (bản Anh: 488.347 block, p99 = 46, max = 84). Trùng khít như vậy khó
là ngẫu nhiên, nên nhiều khả năng đây là hằng số trong engine.

Chưa chứng minh được. Tiếng Việt có dấu tốn 2 byte mỗi chữ nên 1.305 câu vượt
trần; `--max-bytes 84` bỏ số đó ra, mặc định thì ghi hết. Danh sách câu quá dài
xuất bằng `--report` để người dịch rút gọn.

> **Đổi kích thước block KHÔNG làm treo game.** Kết luận cũ ghi trong
> `portjp2us.py` là sai: các lần treo trước đó là do ghi **đúng câu vào sai
> chỗ** (dò theo nội dung rồi dóng lệch một ô), không phải do block dài ra.
> `applyen.py` ghi 94.497 dòng nguyên độ dài, `check()` / `check_pointers()`
> sạch trên cả 54 file.

## Tool phụ

### `ffu.py` — đọc/ghi `.ffu`

```bash
python ffu.py font.ffu "Aáàả"   # in metric từng glyph
```

Cũng là thư viện: `load()`, `index()`, `bitmap()`, `to_png()`, `build()`.
`build()` giữ nguyên chiều cao ô nên chỉ hợp sửa glyph lẻ — đổi chiều cao thì
dùng `ffugen.py`.

### `patchstr.py` — sửa `.gstr` tại chỗ

Ghi đè đúng ô cũ, nên chuỗi mới phải **≤ chuỗi cũ tính theo byte UTF-8**. Nhanh
và không đụng bảng offset, nhưng tiếng Việt có dấu thường dài hơn tiếng Anh nên
phần lớn trường hợp phải dùng `gbnl.py`.

### `vnfont.py` — ghép dấu từ glyph gốc

Hướng làm **cũ**, giữ lại làm đường lui. Nó không render từ font ngoài mà cắt
dấu từ chính glyph của game rồi chồng lên thân chữ:

| dấu | nguồn |
|---|---|
| huyền, sắc, ngã, mũ | `à á ã â` và bản hoa |
| breve (`ă`) | cung đáy chữ `o` |
| nặng | chấm của `.` |
| horn (`ơ ư`) | dấu nháy cong `’` |
| hỏi | **dấu phẩy lật ngang** |

Ưu điểm là giữ 100% nét gốc; nhược điểm là dấu ghép nhìn không đẹp bằng font
dựng sẵn. `draw_hook()` bên trong chỉ là đường lui cho font không có dấu phẩy.

### `translate_glossary.py` — bản dịch mẫu

Vá vài màn để kiểm tra render: menu title, Glossary, thanh phím, và khung Sample
trong Options → Display → Font. Câu trong khung Sample cố ý gom đủ 5 dấu thanh,
mũ, breve, horn, `Đ` và `Ở` hoa (horn + hỏi — tổ hợp chật nhất), để so 4 font
chỉ bằng một màn hình.

Đây là script gắn với Virche; game khác thì viết script riêng.

## Phụ thuộc

`Pillow` (render + scale glyph), `fontTools` (đọc cmap để biết font có ký tự
nào). Chỉ `ffugen.py` cần `fontTools`.
