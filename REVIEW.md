# 工程实现审查报告（对照 REQUIREMENTS.md）— 第二轮复查

> **2026-10-07 更新说明**：下文为 2026-09-29 的历史审查记录，不代表当前待办清单。
> 其中「新-1」「新-2」「新-4」已有代码修复，「新-3」的升级限制已在 INSTALL.md 中说明。
> 本次进一步修复未登录 POST 被 CSRF 检查遮蔽而返回 403 的问题，以及非 ASCII
> CSRF token 导致 500、雇主列表把过期时段标为 available 的问题；新增原始请求
> 和时段到期回归测试。SPEC.md 同步实际权限分层及响应优先级，INSTALL.md 更正
> Alice 的种子技能为 Python、SQL。本轮 Docker 构建成功，容器内执行
> `python -m pytest tests/unit -q`：**37 passed**（仅 pytest 缓存目录权限警告，
> 不影响测试结果）。下文测试数量为历史值。

- **审查对象**：本目录（Team_XYZ / TalentMatch，Flask + SQLite 实现）
- **审查依据**：`CSC4801_final_project/REQUIREMENTS.md`（仅强制 **MUST / MUST NOT**；**MAY** 项不作要求）
- **复查范围**：修复提交 `d7d0eba`（相对首轮审查基线 `da647e3`，18 个文件 +293/−149）
- **复查方式**：逐文件 diff 走读 + 运行单元测试（**26 passed**）+ 全部原问题的运行时复验（Flask test client 实证）
- **复查日期**：2026-09-29

---

## 一、首轮问题复查结论：8 项全部解决 ✅

| # | 原问题 | 状态 | 修复方式与复验证据 |
|---|---|---|---|
| 1 | `GET /jobs/<id>/edit` 缺属主校验，越权泄露他人岗位（FP-EMP-2 / FP-AUTH-3 / FP-SEC-1） | ✅ 已解决 | `app/routes/employer.py::edit_job` 在渲染前调用新增的 `jobs_service.get_owned_job()`（GET 与 POST 校验失败重渲染分支均覆盖）；`applicants` 路由同步加固。复验：外雇 GET 编辑页 → **403**，页面不含对方标题/描述；新增测试 `test_security.py`（GET edit 403）与 `test_workflows.py`（403 且内容不泄露） |
| 2 | 完整实现不在 `main` 分支（FP-SUB-1） | ✅ 已解决 | 修复提交 `d7d0eba` 已在 **`main`** 并推送至 `origin/main`（`https://github.com/XinyuYuan111/CSC4801_Team_XYZ`）。提交时仍须在课程平台提交**最终评分 commit** 的永久 URL（流程性事项） |
| 3 | `SPEC.md` 声称雇主可 GET `/applications/<id>` 但实现 403（FP-PROC-1） | ✅ 已解决 | 采用「改实现对齐 SPEC」：`app/routes/candidate.py::application_detail` 改为 `@login_required`，候选人属主与雇主属主分流（`get_application_for_candidate` / `get_application_for_employer`），模板以 `can_book` 隐藏雇主视图的预约 UI；SPEC/README 同步更新。复验：雇主属主 → **200**（含岗位信息、无预约表单）；外雇 → **403**；其他候选人 → **403**；缺失 → **404**；未登录 GET → **302**、POST → **401**。新增测试见 `test_workflows.py::test_fp_emp_3_*` |
| 4 | 并发重复投递可能 500（FP-CAN-3 文档承诺 409） | ✅ 已解决 | `apply_to_job` 改为「直接 INSERT + 捕获 `IntegrityError` → 409 `Application already submitted`」，以 `UNIQUE(job_id,candidate_id)` 作为竞态安全的重复检测。复验：重复 POST `/jobs/<id>/apply` → **409** 且消息正确 |
| 5 | `authenticate()` 返回含 `password_hash` 的整行（FP-AUTH-2 纵深） | ✅ 已解决 | 改为只取 `id, email, role` 返回（hash 不出模块）；测试断言返回键集 |
| 6 | `delete_job` / `delete_slot` 依赖检查不在事务内 | ✅ 已解决 | 两处检查与 DELETE 移入同一 `BEGIN IMMEDIATE` 事务；并将 schema 依赖外键改为 **`ON DELETE RESTRICT`**（`app/db.py`，applications/interview_slots/bookings），IntegrityError 映射 409。复验：带依赖删除 → **409**；对已订时段/有申请岗位的裸 DELETE → `IntegrityError`（数据库兜底生效）；删已订时段 → **409** |
| 7 | FP-DOC-3「two jobs with required skills」解读风险 | ✅ 已解决 | `app/seed.py` 重排种子数据：Backend Engineer（python,sql）+ Frontend Engineer（javascript）两个**带技能**岗位，另增 Open Application（空技能）作为 FP-MATCH-1 示例 4 载体；Alice 技能改为精确「Python, SQL」使示例 1 成为字面 (C=R) 对。复验：3 个岗位、2 个带技能；四示例成立；README/INSTALL/test_seed 同步 |
| 8 | 种子文案与实际技能不一致 | ✅ 已解决 | 实际技能与 `manage.py` 输出、README、INSTALL、seed docstring 现已全部一致（Python, SQL） |

**回归验证**：`python -m pytest tests/unit -q` → **26 passed**（原测试函数全部保留并扩展了断言；README 需求–测试映射表的测试名未变，仍逐条对应）。

---

## 二、本轮新发现的问题（均为轻微项，无 MUST 硬性不满足）

### 新-1（低）｜`register_user` 并发重复注册仍可能 500

- **文件**：`app/services/auth.py` → `register_user()`
- **功能**：邮箱唯一性（FP-AUTH-1）
- **描述**：与已修复的 `apply_to_job` 旧模式相同——先 `SELECT` 查重再 `INSERT`。正常路径返回 409 `Email already submitted`…（实测 409 `Email already registered`，含大小写变体）；但两个请求同时通过查重时，`UNIQUE(email)` 抛出的 `IntegrityError` 未被捕获 → 500。唯一性本身由约束保证（FP-AUTH-1 成立），仅竞态响应码不优雅。**建议**：与 `apply_to_job` 一样把 INSERT 的 `IntegrityError` 映射为 409。
- **不构成 MUST 违规**：FP-AUTH-1 只要求标识唯一；测试覆盖的正常路径行为正确。

### 新-2（低）｜非 UNIQUE 类 `IntegrityError` 的边缘竞态仍会 500

- **文件**：`app/services/applications.py::apply_to_job`、`app/services/scheduling.py::book_slot`
- **描述**：两处的 `except sqlite3.IntegrityError` 只把含 `"UNIQUE"` 的错误映射 409，其余（如 FK RESTRICT：目标岗位/时段在请求间隙被并发删除）原样抛出 → 500。因删除侧已有 `BEGIN IMMEDIATE` + RESTRICT，触发窗口极小。**建议**（可选）：FK 类错误映射 409/404。

### 新-3（低）｜旧数据库不会自动获得 RESTRICT 外键，`init-db` 不迁移 schema

- **文件**：`app/db.py::init_db`（`CREATE TABLE IF NOT EXISTS`）、`INSTALL.md`（「Repeat after every code pull that changes `app/db.py`」）
- **描述**：外键动作（CASCADE→RESTRICT）的变更对**已存在**的 `data/app.sqlite3` 不生效——SQLite 的 `CREATE TABLE IF NOT EXISTS` 不会重建表，只有 `manage.py seed`（`reset_db` 整库重建）后 RESTRICT 兜底才存在。本次修复后的测试均新建库，故全部通过；干净检出、Docker 首次启动也不受影响。但 INSTALL 中「pull 后重跑 `init-db` 即可」的说法对**本次** schema 变更不成立。
- **建议**：在 INSTALL 的升级说明中注明「涉及 `app/db.py` 表结构变更时需重跑 `python manage.py seed`（或提供重建步骤）」。

### 新-4（极低）｜雇主视图的「Back to applications」链接指向候选人专用页

- **文件**：`app/templates/candidate/application_detail.html`
- **描述**：新增的雇主只读视图复用该模板，底部「Back to applications」指向 `candidate.applications`（`@role_required("Candidate")`），雇主点击后落在 403 页。纯 UX 瑕疵，无安全/合规影响。
- **建议**：按 `current_user.role` 分流返回链接（雇主回 `/employer/jobs` 或对应 applicants 页）。

---

## 三、第二轮排查覆盖说明（未再发现问题的区域）

本轮针对修复引入的新代码与此前未深挖的边界做了复查，以下均已核验无问题：

- **新 `application_detail` 双角色路径**：401/302、403、404 契约逐项实测（见上表问题 3）；雇主视图不泄露简历文本（`_application_detail` 不含 `resume_text`）；预约 UI 由 `can_book` 门控。
- **RESTRICT 外键改动的连带影响**：`reset_db` 的 drop 顺序（bookings→…→users）与 RESTRICT 兼容；`seed`/`world` fixture 重建库正常；无用户删除功能，CASCADE→RESTRICT 无功能回退。
- **`get_owned_job` 重构**：无 `_require_owned_job` 残留引用；`update_job`/`delete_job`/`applicants`/`edit_job` 调用点一致。
- **重复注册/重复申请的正常路径**：409 + 文档化消息（含邮箱大小写变体）。
- **安全面回归**：CSRF、SQL 参数化、Jinja 自动转义、密码哈希出栈防护均未被新改动破坏（模板仅新增布尔 `can_book`）。
- **文档一致性**：SPEC 路由表、409 语义、所有权说明与实现一致；README 映射表更新后测试名仍逐条存在；INSTALL/README 种子数据描述与 `seed.py` 一致。
- **测试套件**：26 passed（约 26 秒，非交互，失败非零退出）；FP-TEST-1 六项覆盖面仍完整。

---

## 四、结论

**首轮提出的 3 个 MUST 级不满足与 5 个轻微问题已全部修复**，且修复质量良好（多处采用「约束/事务/数据库兜底」而非仅补 if 判断，并补齐了回归测试）。当前未发现任何 MUST 级不满足项。

剩余 4 个轻微建议项（新-1～新-4）均不构成 REQUIREMENTS.md 的 MUST 违规，可按时间自行取舍。提交前唯一待办（流程性）：将**最终评分 commit 的永久 URL**（`https://github.com/XinyuYuan111/CSC4801_Team_XYZ/commit/<40位sha>`，指向 `main` 上的提交）提交至课程平台，并建议按 FP-SUB-1 的清单在干净环境过一遍 Docker 构建 → 启动 → seed → 测试 → 冒烟流程。
