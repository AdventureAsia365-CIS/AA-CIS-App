# AA-460 — fix test_wordpress() false-positive (chỉ check status 200, không validate response thật)

(Task prompt as given, saved verbatim per repo convention.)

Bug: `test_wordpress()` chỉ kiểm tra `status_code == 200`, không xác nhận response thật là
WordPress JSON. Bất kỳ server nào trả 200 với HTML tại đúng path (anti-bot challenge, trang bảo
trì, WAF/CDN interstitial) đều bị báo "thành công".

## Fix

Success check cần 3 điều kiện: `content-type` bắt đầu `application/json` VÀ body parse được VÀ
có field `id`. Không thoả → rơi vào `_classify_test_failure()` đã có sẵn, thêm 1 nhánh mới vào
đúng hàm đó (không viết logic riêng lẻ).

## Verify (live, site `aa-wordpress.rf.gd`)

- Lấy Application Password mới qua Playwright automation (cũ đã bị revoke).
- Re-run 4 kịch bản: đúng (success:true), sai 1 ký tự / rác / thiếu khoảng trắng (cả 3 phải
  success:false).
- Verify lại kịch bản 404 (`example.com`) vẫn đúng.
- Verify UI: dấu tick xanh chỉ hiện khi thật sự verified.
- Dọn dẹp: xoá test data, revoke Application Password trên site thật.

Sau khi xong: đóng AA-460, cập nhật AA-457 xác nhận đóng được hoàn toàn nếu không còn gì treo.

KHÔNG đụng AA-458 trong task này.
