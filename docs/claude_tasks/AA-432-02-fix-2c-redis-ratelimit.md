## Task cho Claude Code: [AA-432] Fix 401 /v1/tours/* — bỏ X-API-Key gate ở API Gateway, chuyển rate-limit/revoke sang Redis theo tenant_id (JWT)

⚠️ Chạy SAU AA-434 trong cùng phiên (Nghiep sẽ chạy tuần tự 2 task trong 1 lượt prompt).
AA-434 chỉ audit, không sửa gì — không có phụ thuộc code giữa 2 task, chỉ là thứ tự chạy
Nghiep chọn. Nếu AA-434 chưa xong khi đọc tới đây, cứ tiếp tục làm AA-432 bình thường.

## Bối cảnh — ĐỌC KỸ trước khi sửa, đây là quyết định kiến trúc đã chốt

STEP0 (`docs/claude_audit/AA-432-api-gateway-401-step0.md`) đã xác nhận root cause 401
trên `/v1/tours/*` (Browse Pool, My Catalog, + toàn bộ `/v1/*` khác — xem báo cáo, phạm vi
rộng hơn 2 route ban đầu tưởng): FE proxy tenant chỉ gửi `Authorization: Bearer <JWT>`,
không gửi `X-API-Key` mà API Gateway TOKEN authorizer (`tenant-key-authorizer`) đòi.

STEP0-2 (`docs/claude_audit/AA-432-per-tenant-api-key-feasibility.md`) investigate 2
hướng ban đầu (a: service-key tĩnh dùng chung, b: đổi authorizer TOKEN→REQUEST để tự verify
JWT) — cả 2 đều bị bác: (a) mất khả năng rate-limit/revoke theo tenant, (b) yêu cầu đổi
loại authorizer qua Terraform + re-verify toàn bộ `/v1/*`, rủi ro lớn trên auth boundary
sống. Rồi investigate thêm phương án per-tenant X-API-Key thật (2a) — bị chặn vì
`shared.tenants` chỉ lưu hash, không lưu lại được plaintext (đúng thiết kế, không nên đổi
vì đó là rủi ro bảo mật mới — xem báo cáo Q4).

**QUYẾT ĐỊNH CUỐI (Nghiep + Claude Chat, 22/08/2026) — đây là hướng ĐÚNG được chọn, không
cần bàn lại kiến trúc, chỉ implement:**

Bỏ hẳn vai trò "gate xác thực" của API Gateway `X-API-Key` cho `/v1/*` — vì đã xác nhận
(STEP0, mục §5) rằng `get_tenant()` trong `v1_tours.py` đã tự giải mã JWT và lấy
`tenant_id` trực tiếp, KHÔNG bao giờ dùng context của gateway authorizer. Nghĩa là lớp
`X-API-Key` hiện tại chỉ là 1 cổng thô trùng lặp, không phải nguồn xác thực thật.

Thay thế: rate-limit + khả năng revoke theo tenant chuyển hẳn sang tầng ứng dụng
(FastAPI), dùng Redis (đã có sẵn, wired trong `main.py` — xác nhận qua STEP0-2 §2c),
key theo `tenant_id` lấy từ JWT đã verify. JWT vẫn là nguồn xác thực user/session duy
nhất, không đổi gì ở đó.

## Repo & branch

Repo: AA-CIS-App (phần FastAPI + có thể cần AA-CIS-Infra cho phần Terraform đổi
authorization type của API Gateway resource — kiểm tra xem repo nào quản lý Terraform
`aws_api_gateway_method`, dùng đúng repo đó cho phần hạ tầng)

Branch hiện tại: main
Tạo branch mới: yes: pqnghiep1354/aa-432-urgentinfra-api-gateway-id-sai-lech-claudemd-vs-production-x
  (branch đã có từ STEP0 trước, dùng tiếp nếu còn tồn tại và chưa merge, hoặc tạo lại nếu
  đã merge/xoá — xác nhận trạng thái branch trước khi bắt đầu)
Merge vào: main

## Files cần đọc trước

- `docs/claude_audit/AA-432-api-gateway-401-step0.md` — đường đi request đầy đủ, resource
  `/v1/{v1_proxy+}` (ANY), authorizerId, identitySource hiện tại
- `docs/claude_audit/AA-432-per-tenant-api-key-feasibility.md` — lý do bác bỏ 2a/2b, đề
  xuất 2c (Redis, không cần recoverable secret)
- `api/routers/v1_tours.py` — hàm `get_tenant()`, xác nhận lại cách nó giải mã JWT, lấy
  `tenant_id` từ đâu (`tenant["sub"]` theo STEP0) — đây là nơi sẽ thêm Redis rate-limit
  check
- `main.py` — nơi Redis client được khởi tạo/wired sẵn (theo STEP0-2 §2c) — dùng đúng
  client này, không tự tạo kết nối Redis mới
- `shared.tenants` schema — cột `rate_limit_rpm` (đã nhắc ở STEP0-2 §5, "một BFF key
  aggregates all tenants' traffic against one row's rate limit unless special-cased") —
  xác nhận giá trị hiện tại cho từng tenant, dùng làm limit thật khi chuyển sang Redis
- Terraform quản lý API Gateway (tìm trong AA-CIS-Infra hoặc tương đương) — resource
  `/v1/{v1_proxy+}`, method ANY, `authorizationType: CUSTOM` — đây là chỗ cần đổi

## Việc cần làm

### Phần 1 — API Gateway (Terraform)

1. Tìm Terraform resource quản lý method `/v1/{v1_proxy+}` ANY — đổi
   `authorization: "CUSTOM"` sang `authorization: "NONE"` (bỏ hẳn authorizer cho route
   này, không đổi sang REQUEST type — đã bác bỏ hướng đó)
2. **Xác nhận không có route nào khác dưới `/v1/*` đang dựa vào context tenant mà
   authorizer trả về** — theo STEP0 đã xác nhận `get_tenant()` tự verify JWT, không dùng
   authorizer context, nhưng double-check code trước khi xoá hẳn để chắc chắn không có
   nhánh nào khác (vd. code cũ/route khác) còn phụ thuộc
3. Plan trước khi apply — dùng `terraform plan`, xem kỹ output, KHÔNG tự ý
   `terraform apply` ngay — để Nghiep review plan trước (giống quy trình
   `terraform-apply.yml` với `workflow_dispatch` đã có, xem CLAUDE.md phần CI/CD)
4. **KHÔNG xoá hẳn Lambda `tenant-key-authorizer`** trong task này — chỉ gỡ nó khỏi route
   `/v1/*`. Nếu có route khác đang dùng nó (kiểm tra trước), giữ nguyên. Dọn dẹp Lambda
   không dùng nữa (nếu xác nhận không route nào dùng) để riêng, không gộp vào task này.

### Phần 2 — FastAPI rate-limit qua Redis

5. Trong `get_tenant()` (hoặc middleware/dependency phù hợp áp dụng cho toàn bộ `/v1/*`),
   sau khi verify JWT lấy được `tenant_id`, thêm check Redis:
   - Key kiểu `ratelimit:{tenant_id}:{window}` (sliding window hoặc fixed window/phút —
     chọn cách đơn giản, khớp cách `rate_limit_rpm` đã định nghĩa trong `shared.tenants`)
   - Nếu vượt limit → trả 429 Too Many Requests (không phải 401 — đây là rate-limit, khác
     nghĩa với lỗi xác thực)
6. Cơ chế revoke theo tenant: xác nhận middleware/`get_tenant()` đã check `is_active` của
   tenant từ DB (hoặc cache ngắn hạn) mỗi request — nếu chưa có, thêm vào (đây là cách
   "revoke" thay thế cho việc xoay API key — set `is_active=false` là đủ để chặn tenant
   ngay lập tức, không cần đợi JWT hết hạn)

### Phần 3 — Update tài liệu

7. `CLAUDE.md` — thêm ghi chú ngắn giải thích kiến trúc mới (JWT-only cho `/v1/*`, không
   còn X-API-Key gate, rate-limit ở tầng app qua Redis) — để tránh ai đọc tài liệu cũ rồi
   hiểu nhầm vẫn cần X-API-Key

## Verify

- Test live: gọi `/v1/tours/pool` với tenant JWT thật (không kèm `X-API-Key`) → phải
  THÀNH CÔNG (200), không còn 401
- Test rate-limit: gọi vượt `rate_limit_rpm` của 1 tenant test → xác nhận nhận 429, không
  phải 401/500
- Test revoke: set `is_active=false` cho 1 tenant test → xác nhận request tiếp theo bị
  chặn (401 hoặc 403, tuỳ code hiện có xử lý sao cho tenant không active)
- Xác nhận các route khác dưới `/v1/*` (không chỉ Browse Pool/My Catalog — xem danh sách
  đầy đủ trong STEP0 §4: DashboardTab, PoolTab, CatalogTab, và staff routes
  `(internal)/catalog`, `(internal)/upload`) đều hoạt động lại bình thường
- Xác nhận `/admin/*`, `/auth/*`, `/content/*` (authorizer NONE từ trước, không đổi bởi
  task này) không bị ảnh hưởng

## Sau khi done

- git commit -m "fix: bỏ X-API-Key gate /v1/*, chuyển rate-limit sang Redis theo tenant [AA-432]" && git push
- **Lưu chính task prompt này vào `docs/claude_tasks/AA-432-02-fix-2c-redis-ratelimit.md`**
  (copy nguyên nội dung task này vào file đó, commit cùng branch) — đây là rule bắt buộc
  đã có trong skill Nghiep, task trước đã bỏ sót
- Lưu báo cáo verify vào `docs/implementation-notes/AA-432-fix-2c-redis-ratelimit.md`
- Paste kết quả verify về Claude Chat
- Linear: AA-432 → In Review (Terraform plan chưa apply thì giữ nguyên trạng thái hiện tại,
  ghi rõ trong comment Linear là đang chờ Nghiep review plan trước khi apply)
