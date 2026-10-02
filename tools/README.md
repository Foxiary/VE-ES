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

`--mark-lift N` nâng dấu thanh của chữ có **hai dấu chồng nhau** lên `N` hàng.
Engine vẽ font ADV ở tỉ lệ 0.588, mà các font Latin chỉ chừa 0–2 hàng trống
giữa dấu thanh và dấu mũ, nên trên màn hình hai dấu dính thành một khối và
trông như bị cắt. Chỉ tác động lên chữ mà dạng NFD có ≥2 combining mark —
đúng tập `ấ ế ồ ắ …`, không đụng `à á è` của Latin-1. Có kẹp theo từng glyph
để không đẩy mực ra ngoài ô; 3 là mức lớn nhất mà chưa chữ thường nào bị kẹp.
Chi tiết ở `../CLAUDE.md`.

`--stroke N` vẽ **viền tối** quanh chữ: đặc `N` px tính từ mép chữ, thêm 1 px
mờ dần. Font ADV gốc có sẵn viền này — palette của nó không phải dải độ phủ mà
là chữ trắng trên viền đen (index 1–3 đen trong suốt dần, 4 đen đặc, 5–15 xám
tới trắng). `--stroke 2` khớp bản gốc: index 4 chiếm 30% điểm mực (gốc 33%),
chữ `H` cao 51 hàng (gốc 52). Mỗi chữ rộng thêm `2×N` px nên câu dài ra ~14%
— đo lại bề rộng bằng `textwidth.py` trước khi bật. Chỉ dùng cho advfont1–4:
palette của sysfont không có màu tối, tool sẽ từ chối.

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

Cột `bytes` là độ dài câu gốc tính theo byte UTF-8, **chỉ để tham khảo**. Không
có trần byte: bản dò đã đẩy dòng 100, 150, 200, 300, 500 và 800 byte lên màn
hình và game chạy hết. Thứ thật sự tràn là **bề rộng khi vẽ ra**, đo bằng
`textwidth.py` — xem mục "Trần là bề rộng" bên dưới. Chữ Việt có dấu tốn 2 byte
mỗi chữ nhưng vẽ ra vẫn là một chữ bề ngang bình thường, nên đếm byte càng sai.

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

#### `--merge` — nạp bản dịch có sẵn vào workbook

```bash
python mksheet.py --merge "Shuuen_JP_STORY.xlsx" --out work/virche_vi.xlsx
```

Nhận bảng dịch đã có **cột `EN ID`** do chính tool này sinh ra, đổ cột Tiếng
Việt vào đúng dòng và thêm hai cột `vi_bytes` + `canh bao`. Ghép **theo ID**
(offset byte chính xác của build đang bung), không cần dò nội dung như
`applystory.py`.

Cột `EN ID` phải tìm **theo tiêu đề**, không tìm theo nội dung được: ID neo theo
bản Nhật (`1___48EFC_text`) và ID bản Anh (`4150___48F08_text`) cùng một dạng,
nên quét nội dung sẽ bám vào cột đầu tiên — tức cột tiếng Nhật — rồi không khớp
được dòng nào.

Các cờ trong cột `canh bao`:

| cờ | nghĩa |
|---|---|
| `khong vua block` | câu dịch cần nhiều byte hơn block gốc |
| `qua dai NNB` | dài hơn 84 byte — **chỉ hiện khi không nạp được font để đo bề rộng**, và đo sai đại lượng |
| `markup lech` | `#NAME[1]` / `#Color[]` / `#n` khác với block bị ghi đè |
| `cau Nhat lech` | câu Nhật dùng để dịch không nằm ở vị trí đó bên bản Nhật |
| `chua dich` | chưa có bản dịch |

Dòng nào cột `Nguon (EN)` trống và cột `Ghi chu` ghi `o trong - ban Nhat co dong
nay` là **ô tiếng Anh bỏ trống**: lệnh vẫn nằm trong file, chỉ là block rỗng.
Đó là chỗ để đặt dòng thừa của bản Nhật, không phải lỗi rút text.

#### `--relink` — dựng lại cột `EN ID` từ chính hai build

```bash
python mksheet.py --merge "Shuuen_JP_STORY (8).xlsx" --relink --out work/virche_vi.xlsx
```

Cột `EN ID` bảng dịch gửi về được zip lần lượt qua những dòng tiếng Anh **có
chữ**, nên cứ bước qua một ô bỏ trống là cả đoạn sau lệch một ô cho tới khi có
gì đó kéo lại. Đo trên bảng `(8)`: 95.019 dòng đúng, 557 dòng lệch ô, 10.277
dòng không có `EN ID` nào — trong đó hơn 7.000 dòng đã dịch xong mà không tool
nào đặt được.

`--relink` bỏ qua cột đó và tự khớp lại (chi tiết ở `relinkjp.py`). Kết quả:
91,6% → **98,5%** số dòng có bản dịch, và 109 tiêu đề chương rác — `...` thay
vì tên chương, đúng cái `applyvi.py` vẫn phải từ chối — biến mất luôn vì chúng
vốn là hậu quả của chính chỗ lệch này. Tiêu đề thật do `filltitles.py` ghép vào
sau, như cũ.

So khớp markup dùng đúng token `#NAME[k]`, `#Color[k]`, `#n`, thay vì regex tham
kiểu `#[A-Za-z]+` (nó nuốt luôn chữ đứng sau `#n` nên `#nto` và `#nand` thành
hai lệnh khác nhau). Trên dữ liệu thật hai cách chỉ lệch nhau **1 dòng mỗi
chiều** — dùng token chính xác vì đúng nguyên tắc, không phải vì nó sửa được
nhiều.

Khi so cột tiếng Nhật, **bỏ hẳn dấu câu** ở cả hai bên chứ không quy đổi từng
dấu: bảng đi qua CSV về thì `……` thành `...`, `――` cũng thành `...`, mất luôn
ngoặc nhấn `【】` và dấu `。` cuối câu. Quy đổi từng dấu vẫn còn **15.699 dòng bị
báo lệch, trong đó 15.420 dòng chỉ khác nhau ở dấu câu** — một cờ to như vậy thì
không ai đọc. Bỏ hết dấu câu còn **278 dòng**, và đó đều là khác thật: tên nhân
vật bảng ghi rõ còn build vẫn để `？？？`, hoặc một động từ đổi giữa hai bản.

### Bộ tool kịch bản đi kèm

- `stcm2l.py` — đọc / dựng lại `.DAT` (STCM2L); chạy trực tiếp để tự kiểm tra file
- `checksheet.py` — đối chiếu bảng dịch với `.DAT`, xem bảng có đúng build không
- `applyvi.py` — ghi workbook của `mksheet.py` vào `.DAT` theo ID (**ưu tiên dùng**)
- `applystory.py` — ghi bản dịch, khớp theo nội dung, khi bảng không có `EN ID`
- `portjp2us.py` — chuyển bản dịch neo theo bản Nhật sang build khác
- `relinkjp.py` — dựng lại cột `EN ID` của bảng neo bản Nhật từ chính hai build
- `chuadich.py` — dòng game còn hiện tiếng Anh, kèm vị trí chèn trong bảng dịch và cả khung thoại

Quy trình: `mksheet.py` → dịch cột C → `mksheet.py --merge --relink` →
`applyvi.py` → `cpk.py repack`.

### `relinkjp.py` — đặt lại địa chỉ cho bảng neo bản Nhật

```bash
python relinkjp.py "Shuuen_JP_STORY (8).xlsx" --report work/relink_loose.csv
```

Chạy riêng thì chỉ báo cáo; muốn dùng thật thì gọi qua `mksheet.py --relink`.

Điều làm được chuyện này là **hai build chung một kịch bản**: 50/54 file giống
hệt nhau từng lệnh một, còn `302` và `402` chênh một lệnh, `605` hai, `601` ba —
`portjp2us.align()` khép nốt bốn file đó. Nên lệnh thứ N bên này là lệnh thứ N
bên kia, và mọi dòng tiếng Nhật đều đã có sẵn ô bên tiếng Anh.

Chỗ tiếng Anh cần ít dòng hơn tiếng Nhật, block bị **để rỗng** chứ lệnh không bị
xóa:

| | lệnh `text` | trong đó có chữ |
|---|---|---|
| bản Anh | 82.685 | 70.787 |
| bản Nhật | 82.692 | 77.655 |

5.989 ô ở giữa là lệnh sống mang block rỗng, và **cả 5.989 ô đều nằm trong khung
thoại đang hiện chữ** (5.935 khung, không khung nào rỗng hoàn toàn). Điền một ô
là thêm một dòng vào khung vốn đã ở trên màn hình, không bao giờ làm hiện ra một
khung trống.

Khớp lại **theo nội dung**, không theo cột ID của bảng: offset trong ID đó chỉ
giải được 43% số dòng với bản Nhật đang có, tức bảng được cắt từ một bản dump
khác. Dùng `difflib` so cột tiếng Nhật với chính block của build Nhật rồi bê
thẳng chỉ số lệnh sang bản Anh — 105.853 dòng đặt được, thêm 24 dòng được trả
lại đúng ID cũ của nó khi hai dòng kề bên bảo đảm cho (`between()`). 85 dòng còn
lại liệt kê ra `--report` chứ không đoán bừa, trong đó 27 dòng có bản dịch.

Bảng dịch theo **bản Nhật 1.0.0**, còn game (bản Anh) theo **1.0.1**, nên thứ tự
câu không phải lúc nào cũng giống nhau. Vì vậy có bốn lượt, lượt trước được tin
hơn: khớp theo thứ tự → `EN ID` của bảng khi hai hàng kề bên bảo đảm
(`between()`) → khớp nội dung bất kể thứ tự cho đoạn 1.0.1 đã đảo
(`reordered()`) → rót lại cả khung khi bản Anh xoá một dòng rồi dồn câu lên ô
trống (`rescue_boxes()`). Đổi thứ tự hai lượt giữa từng làm sai 3 ô ở `206`.
Mỗi lần sửa ở đây, so toàn bộ bảng trước/sau: lượt đúng chỉ đổi đúng những ô
định sửa.

Hàng không có ID ở cột A (nhóm dịch chèn tay) vẫn được đọc, với ID tạm
`+<dòng Excel>`. Hàng ID `…_text10` là một dòng `var`. Khi hai hàng rơi vào cùng
một ô, hàng trống không đè hàng đã dịch.

### `chuadich.py` — dòng game còn hiện tiếng Anh

```bash
python chuadich.py "<bang dich>" work/virche_vi.xlsx work/chua_dich.xlsx
```

Liệt kê cả những dòng mà bảng không có hàng nào (ô bản Anh để trống, hoặc dòng
chỉ có ở 1.0.1), kèm "chèn sau / trước dòng Excel" và ba cột "Ca khung". Dòng
chỉ gồm `　#n` là dòng đệm, không liệt kê.

### `applyvi.py` — ghi bản dịch theo ID

```bash
python applyvi.py work/virche_vi.xlsx STORY.cpk work/story-vi-en
python applyvi.py work/virche_vi.xlsx STORY.cpk out --dry-run
python applyvi.py work/virche_vi.xlsx STORY.cpk out --max-bytes 84 --report qua_dai.csv
```

Không dò nội dung: ID trong workbook đã là offset byte chính xác của block nên
mỗi dòng tự chỉ đúng đích — 28.141 dòng "ambiguous" khi khớp theo nội dung thì ở
đây là chính xác. Offset vẫn kiểm lại: block phải đang chứa đúng câu ở cột
nguồn, lệch thì bỏ qua và đếm.

Mỗi file sau khi dựng lại phải qua kiểm tra mới được ghi ra đĩa — walk dừng đúng
`EXPORT_DATA`, không byte khác 0 bị bỏ, không con trỏ lạc, **và đồ thị gọi hàm y
nguyên**. Trượt thì không ghi.

### Trần là bề rộng, không phải byte

Bản Nhật và bản Anh biên dịch độc lập mà **cả hai đều không có block text nào
quá 84 byte** (bản Anh: 488.347 block, p99 = 46, max = 84). Trùng khít như vậy
trông hệt như một hằng số trong engine, và tài liệu này từng ghi nó là hạn mức.

**Không phải.** Bản dò đặt dòng 100, 150, 200, 300, 500 và 800 byte vào phần mở
đầu; game chạy qua hết. 84 byte chỉ là chỗ text tiếng Anh gốc dừng lại. Thứ nó
làm là vẽ chữ tràn ra ngoài mép phải màn hình — khung tràn theo **bề rộng**.

Đo bằng `textwidth.py`, cộng advance của từng glyph trong `.ffu`, so với khung
hẹp nhất là backlog (2430 đơn vị) vì mọi câu thoại đều được chiếu lại ở đó. Phải
đo bằng **font sẽ ship**, không phải font gốc — hai bộ lệch nhau tới 15% và sai
cả thứ tự giữa các font.

`--report` xuất danh sách câu **tràn khung**; `--fit-width` bỏ hẳn chúng.
`--max-bytes` vẫn còn cho quy trình cũ nhưng đo sai đại lượng.

### Con trỏ gọi hàm — vì sao block dài ra từng làm treo game

`portjp2us.py` ghi nhận: thay chuỗi **cùng kích thước** thì chạy, hơn hoặc kém
một byte là treo, còn sửa đúng lệnh cuối cùng (phía sau không còn gì để dời) thì
lại chạy. Triệu chứng đó là dấu hiệu kinh điển của **con trỏ chết**, và đúng là
vậy:

> Khi `global_call == 1`, trường thứ hai của lệnh **không phải opcode** mà là
> **địa chỉ của lệnh cần gọi**. `stcm2l.build()` trước đây chép thẳng giá trị đó
> sang file mới mà không dời.

Bản tiếng Anh có **350.273/718.773** lệnh là lời gọi, 100% trỏ đúng đầu một lệnh
khác. Cho các block text của `101.DAT` dài ra rồi dựng lại kiểu cũ: **6.539**
con trỏ gọi rơi vào giữa lệnh khác; tính trên 6 file đầu là **90,7%**.

**Kết luận cũ ở đây — "đổi kích thước block không làm treo game, vì `check()` và
`check_pointers()` sạch" — dựa trên bằng chứng không đủ.** Hai hàm đó không hề
đọc trường opcode. File dựng kiểu cũ vẫn cho `walk lands = True`, `byte khác 0 =
0`, `check_pointers() = 0` trong khi 6.539 lời gọi đã hỏng. Mọi bản build tạo
trước khi sửa `stcm2l.build()` đều dính lỗi này.

`stcm2l.build()` giờ dời cả trường đó. `Script.call_targets()` biểu diễn đồ thị
gọi bằng **chỉ số lệnh** nên so được trước/sau khi dựng lại, và
`Script.check_calls()` đếm con trỏ gọi không trúng đầu lệnh. Round-trip không
sửa gì vẫn `BIT-IDENTICAL`.

Sau khi sửa thì block dài ra **thật sự an toàn về mặt cấu trúc**: 54 file, +1,13
MB, đồ thị gọi y nguyên, mọi kiểm tra sạch.

### `exefs.py` — đọc chữ nằm ngoài romfs

```bash
python tools/exefs.py extract  "...[USA][v0].nsp" work/exefs   # can prod.keys
python tools/exefs.py segments work/exefs/main work/exefs
python tools/exefs.py strings  work/exefs/main.rodata.bin --grep "
 
"
python tools/exefs.py sheet    work/exefs/main.rodata.bin --grep "
 
"
```

`sheet` dung `Workbook` của `mksheet.py` nên cột giống mọi sheet khác,
nhưng ID cố tình đặt dạng `main.rodata___2BD34_exe` để **không tool nào
lỡ áp vào**: nó trượt regex của `checksheet.py`, `applyvi.py` lẫn
`applyui.py`. Mấy dòng này không trỏ tới block `.DAT` hay ô `.gbin` nào.

Ngắt dòng ở đây là **xuống hàng thật và phải giữ nguyên** —
`linebreak.to_game()` sẽ biến nó thành `#n`, sai cho chỗ này.

Không có cột tiếng Nhật: bản JP không giữ câu nào trong file thực thi
(đã kiểm cả `main` lẫn `subsdk0` của hai bản), nên mấy câu này có vẻ là
thứ bên bản địa phương hóa thêm vào.

Màn tiêu đề hiện một câu trích của ending vừa phá, và cả **12 câu** nằm
trong `.rodata` của `exefs/main`, không ở CPK nào. Kết luận này là do
**loại trừ**: đã quét 22 database trong SYSTEM.cpk, 117 script trong
STORY.cpk, `SaveUtil/`, `Shader/` — tất cả đã giải nén; GAME.cpk thì chỉ
có `.tid` và `.CL3`.

Chúng viết khác mọi chuỗi còn lại: ngắt dòng là `
` thật chứ không
phải `#n`, và giữa hai đoạn là `
 
` — đó là dấu hiệu để tìm ra.
124–252 byte mỗi câu, đã xuất ra `work/title_quotes.csv`.

Đi qua `nsz` (đã cài sẵn, có bộ đọc NCA), khóa lấy từ
`~/.switch/prod.keys`. `main` là NSO, ba segment nén LZ4 block — bộ giải
nén viết tay ~30 dòng, rẻ hơn thêm một dependency, và có đối chiếu
kích thước với header.

**Vá chỗ này là việc khác.** Mod CPK không với tới file thực thi;
Ryujinx nạp nó từ `mods/contents/<title id>/<tên>/exefs/`. Và `.rodata`
xếp khít không có chỗ trống, nên câu thay phải **vừa đúng số byte cũ**
— khá chật với tiếng Việt.

### `tid.py` — đọc texture `.tid` trong GAME.cpk

```bash
python tools/tid.py list   GAME.cpk
python tools/tid.py list   GAME.cpk TITLE
python tools/tid.py unpack GAME.cpk TITLE/ work/tid
```

GAME.cpk không có file text nào — 714 texture `.tid` và 777 sprite `.CL3`.
Header 128 byte, `width` ở 0x44, `height` ở 0x48, FOURCC ở 0x64:
`DXT1` (0,5 byte/px), `DXT5` / `BC7 ` (1,0), hoặc **bốn byte NUL** — không
phải format nén mà là **BGRA 32-bit thô**.

**Dữ liệu xếp tuyến tính, không swizzle.** Texture Switch thường lưu
block-linear, phải gỡ tile trước khi giải mã. Cái này thì không, nên
Pillow đọc thẳng và `tid.py` chỉ là bộ đọc header. Đây là **kiểm chứ**
chứ không phải đoán: block đầu của `title_bg1.tid` ra màu liền mạch
chứ không rời rạc như khi bị tile, rồi đem so với ảnh chụp màn hình.

`list` in `width x height x byte/px` so với payload từng file, nên header
đọc sai sẽ hiện ra thành lệch kích thước chứ không thành ảnh sai.

**Rất nhiều chữ giao diện được vẽ thẳng vào ảnh.** Cả thanh menu màn
tiêu đề (Start, Load, Flowchart, Scene List, Special, Options) nằm trong
một atlas BC7 2048x1024, mỗi mục 3 trạng thái, kèm logo, "Press Any
Button" và dòng copyright. Chữ "Glossary", "Notes", "-NEW-" nằm trong
`dictionary_parts.tid`; tên nhân vật nằm trong `chsel_face*.tid`.
`mksheet.py` không thể với tới — dịch mấy cái đó là **vẽ lại**.

**Ghi ngược chưa làm được.** Pillow giải mã BCn nhưng không mã hóa,
nên muốn nhét atlas đã vẽ lại vào game thì cần thêm bộ nén.

### `applyui.py` — ghi dòng giao diện vào SYSTEM.cpk

```bash
python tools/applyui.py work/glossary.xlsx work/out
python tools/applyui.py work/virche_vi.xlsx work/out --dry-run
python tools/applyui.py work/glossary.xlsx work/out --cpk dist/SYSTEM_text.cpk
```

Cặp đôi của `applyvi.py` cho nửa text còn lại. `applyvi.py` vá block `.DAT`
trong STORY.cpk và **cố tình** không nhận dòng `ui`; tool này lấy đúng những
dòng đó và dựng lại file `.gbin` / `.gstr` sinh ra chúng.

Ghi ra **thư mục**, tức bước 3 của `build.py` — đúng chỗ
`translate_glossary.py` đang đứng, và đúng thư mục `cpk.py repack` góm vào CPK
cùng với font. `--cpk` chỉ là lối tắt để xem thử một màn, không cần build lại
cả bản.

`--src` mặc định là `SYSTEM.cpk` chứ không phải `work/stock`, vì stock chỉ có
4 file ghi trong `fonts.json` — riêng màn Glossary đã đụng `strGame.gstr`
không nằm trong đó.

**Địa chỉ theo ID, và ID được kiểm.** `translate_glossary.py` dò theo nội dung —
tìm chuỗi tiếng Anh ở bất kỳ đâu trong pool. Đó chính là cách `CLAUDE.md` cảnh
báo. ID của mksheet là một địa chỉ (`bản ghi.cột___offset_role`) nên một dòng
chỉ thẳng ô của nó. Cả ba phần đều phải đúng trước khi ghi: ô phải tồn tại,
phải còn trỏ đúng offset đó, và chuỗi ở đó phải là câu nguồn trong sheet.

**Một dòng sửa mọi ô trỏ vào chuỗi đó.** `gbnl.build()` khóa theo nội dung chứ
không theo ô. Vì vậy hai dòng cùng câu nguồn mà khác bản dịch thì **bị từ
chối** — cái nào thắng cũng là lặng lẽ quyết thay cái kia.

**Dài bao nhiêu cũng được** — pool được dựng lại, không có trần như block
`.DAT`. Cái file không sống nổi là mất khối schema, nên kết quả được **đọc lại
và so từng ô** trước khi ghi xuống đĩa (`verify()`): shape không đổi, khối schema
giống từng byte, và mọi ô phải đọc ra hoặc bản dịch hoặc đúng cái cũ.

Đo thử trên một sheet Glossary điền tay: 4 dòng được áp, đúng **5 ô** đổi trong
`dbDictionary` (một mô tả + hai tên, mỗi tên ăn cả cột 8 lẫn 16), 1 ô trong
`strSystem`, khối schema nguyên vẹn. Dòng thêm `#NAME[1]` bị chặn vì lệch
markup; dòng dịch trùng bản gốc bị bỏ qua. Đóng gói lại rồi so toàn bộ CPK:
54/54 file, đúng 2 file khác — hai file vừa sửa.

### `linebreak.py` — `#n` ↔ xuống hàng thật

Trong game, ngắt dòng là `#n`. Trong ô Excel thì nó thành một cục chữ dài,
người dịch muốn ngắt lại phải đếm ký tự không nhìn thấy. Nên lúc ghi sheet,
`to_sheet()` đổi `#n` thành xuống hàng thật; lúc đọc sheet, `to_game()` đổi
ngược lại. `mksheet.py`, `glossary.py`, `checksheet.py`, `applyvi.py` và
`reflow.py` đều đã nối sẵn.

Đổi qua đổi lại **không mất gì**, và điều đó được **đếm trước khi dùng**:

- Không chuỗi nào trong game chứa ký tự điều khiển thô — quét đủ **97.110**
  dòng `mksheet.py` rút ra, đếm được **0**. Nên xuống hàng trong ô chỉ có thể
  do `to_sheet()` hoặc người dịch tạo ra, đổi ngược không thể đẻ thêm `#n`.
- `#n` là lệnh duy nhất viết bằng `n` thường. Cả bản game chỉ có `#NAME[1]`,
  `#Color[0]`, `#Color[8]`, `#PosX[%d]`, `#ERROR` và `#n`.

**Khoảng trắng cạnh chỗ ngắt giữ nguyên** — 54 dòng gốc có dấu cách trước
`#n`, 4 dòng có sau. Cắt cho gọn là sửa nội dung, nên không cắt. Chỗ gọi
`.strip()` cả ô **trước** khi `to_game()`, để cái xuống hàng thừa ở cuối ô
(Excel không hiện) không biến thành `#n` ở cuối câu.

Cột `bytes` đếm **trước** khi đổi: ngắt dòng tốn 2 byte trong game, 1 trong ô.

Sheet làm từ trước vẫn chạy y nguyên — trong đó `#n` là chữ thật, `to_game()`
không đụng tới. Kiểm trên `work/virche_vi.xlsx`: 0/192.711 ô bị đổi.

### `glossary.py` — bảng dịch riêng màn Glossary

```bash
python tools/glossary.py --out work/glossary.xlsx
```

Màn Glossary lấy chữ từ ba file: `dbDictionary.gbin` (98 mục, tên + mô tả),
`strSystem.gstr` (thanh tab kana, câu báo tab rỗng, hai dòng gợi ý ở menu) và
`strGame.gstr` (câu báo mở khóa hết). `mksheet.py --no-story` đã rút
`dbDictionary` đủ, nhưng không lọc được hai file kia — riêng `strSystem` có
114 dòng của mọi màn khác. Tool này liệt kê tay 5 khóa trong `UI_KEYS`.

Cột và ID lấy thẳng từ `mksheet.py` (import `Workbook`, `db_rows`,
`db_pairing`, `jp_db_map`) chứ không chép lại, vì `checksheet.rows_of()` đọc
cột nguồn và cột dịch **theo vị trí**.

**196 dòng cho 294 ô là đúng.** `dbDictionary` có ba cột chuỗi: tên (8), cách
đọc (16), mô tả (24). Bản tiếng Anh để cột 8 và 16 **trỏ chung một chuỗi** ở
cả 98 bản ghi — bản Nhật để kana ở cột 16 cho việc sắp xếp, tiếng Anh không có
gì để bỏ vào. `gbnl.build()` khóa theo nội dung nên một dòng sửa cả hai ô.

**Thanh tab vẫn là tiếng Nhật.** `IDS_DICTIONARY_TAB` giống hệt nhau ở cả hai
bản: mười mốc `#PosX[%d]` chứa あ-わ. `u16` ở offset 2 của bản ghi là hàng kana
của **cách đọc tiếng Nhật** — khớp 98/98 — nên dịch chuỗi không đổi được cách
gom nhóm, đó là việc ghi lại cột đó, khác việc dịch.

Ghi bảng này ngược vào game bằng `applyui.py`.

## Tool phụ

### `ffu.py` — đọc/ghi `.ffu`

```bash
python ffu.py font.ffu "Aáàả"   # in metric từng glyph
```

Cũng là thư viện: `load()`, `index()`, `bitmap()`, `to_png()`, `build()`.
`build()` giữ nguyên chiều cao ô nên chỉ hợp sửa glyph lẻ — đổi chiều cao thì
dùng `ffugen.py`.

### `translate_glossary.py` — bản dịch mẫu

Vá vài màn để kiểm tra render: menu title, Glossary, thanh phím, và khung Sample
trong Options → Display → Font. Câu trong khung Sample cố ý gom đủ 5 dấu thanh,
mũ, breve, horn, `Đ` và `Ở` hoa (horn + hỏi — tổ hợp chật nhất), để so 4 font
chỉ bằng một màn hình.

Đây là script gắn với Virche; game khác thì viết script riêng.

## Phụ thuộc

`Pillow` (render + scale glyph), `fontTools` (đọc cmap để biết font có ký tự
nào). Chỉ `ffugen.py` cần `fontTools`.
