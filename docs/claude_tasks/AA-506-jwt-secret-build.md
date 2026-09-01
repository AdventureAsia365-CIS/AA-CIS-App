[Ghi chú phục dựng: bản chat gốc gửi phiên Claude Code trước đã mất theo `/clear`, không nằm
trong context phiên ghi file này. Nội dung dưới đây là Linear issue description của AA-506
(nguồn thật duy nhất còn truy xuất được, lấy qua Linear MCP `get_issue`) — AA-506 không có riêng
một comment "chốt thiết kế" tách biệt (khác AA-508/509) vì issue Urgent này đã có đủ "Việc cần
làm" cụ thể ngay trong description, không qua vòng STEP0 riêng. Không đảm bảo khớp 100% byte cho
byte với prompt đã gõ vào chat, nhưng là nội dung thật, không suy diễn.]

---

# [SECURITY][Urgent] JWT_SECRET hardcoded fallback đang sống trên production — bất kỳ ai đọc code đều giả mạo được JWT cho mọi tenant

## Nguồn gốc

Phát hiện ngoài scope trong lúc live-verify AA-501 (30/08/2026) — không phải bug do AA-501 gây
ra, nhưng nghiêm trọng hơn nhiều so với AA-501 nên tách issue Urgent riêng.

Đã từng thấy sơ qua ở S157 (23/08/2026, lúc làm AA-449) nhưng khi đó chỉ là **dev container**
không set `JWT_SECRET`, được ghi nhận là "future ticket, không sửa ngay". Lần này Claude Code xác
nhận qua `describe-task-definition` + env của container đang chạy thật: **production task
definition** `aa-cis-dev-api` **(task hiện tại :172) cũng KHÔNG set** `JWT_SECRET` — không còn là
vấn đề riêng dev nữa.

## Mức độ nghiêm trọng

`api/routers/auth.py` có 1 fallback string hardcode ngay trong source
(`"cis-dev-jwt-secret-change-in-prod"`) dùng khi env `JWT_SECRET` không tồn tại. Vì biến env này
KHÔNG được set trên task definition thật, **mọi JWT tenant thật hiện tại đang được ký bằng đúng
chuỗi hardcode đó** — công khai trong source code (ai clone/đọc được repo, kể cả qua GitHub nếu
lỡ public, hoặc bất kỳ ai có quyền đọc code) đều có thể tự ký JWT hợp lệ cho BẤT KỲ tenant nào,
bỏ qua hoàn toàn bước xác thực qua API-key login.

So sánh: `ADMIN_SECRET` đã đúng — wired qua Secrets Manager, không hardcode. `JWT_SECRET` cần
đúng cách xử lý tương tự.

## Việc cần làm

1. Tạo secret mới trong Secrets Manager (namespace tương tự `aa-cis/dev/openai-key` đã có tiền lệ)
   — giá trị random đủ mạnh (không phải chuỗi dễ đoán), **KHÔNG hardcode vào code/task
   definition/terraform** — theo đúng quy trình đã dùng khi xoay OpenAI key trước đây (S153).
2. Cập nhật task definition `aa-cis-dev-api` để inject `JWT_SECRET` từ Secrets Manager (giống
   cách `ADMIN_SECRET` đã làm — dùng lại đúng pattern, đừng phát minh cách khác).
3. Force new deployment — xác nhận task mới thật sự load secret mới (không phải rollback về task
   cũ dùng fallback do secret fetch lỗi).
4. **Hệ quả cần xử lý:** đổi `JWT_SECRET` sẽ làm MỌI JWT tenant hiện tại (ký bằng secret cũ/
   fallback) hết hiệu lực ngay lập tức — mọi tenant đang đăng nhập sẽ bị logout, cần đăng nhập
   lại. Xác nhận với Nghiệp thời điểm thực hiện phù hợp (off-peak nếu có tenant thật đang dùng)
   trước khi force deploy — đây là điểm khác biệt so với việc xoay OpenAI key (không có tác động
   phía người dùng cuối).
5. Sửa code `auth.py`: loại bỏ hẳn fallback string hardcode — nếu `JWT_SECRET` không có trong
   env, app phải fail-fast khi khởi động (raise lỗi rõ ràng) thay vì âm thầm dùng giá trị đoán
   được. Đây là nguyên nhân gốc — nếu chỉ đổi secret mà giữ fallback, lỗ hổng vẫn tồn tại tiềm ẩn
   cho môi trường tương lai (staging mới, task definition mới quên set biến).

## Live-verify bắt buộc trước khi Done

* Xác nhận JWT ký bằng secret cũ/fallback bị từ chối (401) sau khi đổi.
* Xác nhận tenant đăng nhập lại được bình thường, nhận JWT mới ký bằng secret mới.
* Xác nhận app KHÔNG khởi động được nếu `JWT_SECRET` thiếu (test riêng, không chạy trên
  production — test trong container tạm/local).
* `describe-task-definition` xác nhận `JWT_SECRET` được inject qua Secrets Manager, không phải
  plaintext trong task definition.

## Liên quan

Không thuộc scope AA-501 — phát hiện độc lập trong lúc live-verify AA-501, không phải bug AA-501
gây ra.

---

## Xác nhận thời điểm thực hiện (comment Linear, 01/09 02:48 UTC, Nghiệp)

Nghiệp xác nhận thời điểm: **làm ngay bây giờ (S169)** — không cần chờ off-peak riêng, chấp nhận
mọi tenant đang login bị logout và cần đăng nhập lại. Chuyển In Progress, giao build prompt cho
Claude Code trong phiên này.
