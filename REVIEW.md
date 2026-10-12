# 工程实现审查报告（对照 REQUIREMENTS.md）

## 2026-10-12 修复复核：以强制需求为准

本节是当前结论；后面的第三轮记录保留为**修复前历史证据**，其中的测试数量、
`xfail`、建议和“无 MUST 违规”结论不代表修复后的状态。此次未修改课程
`CSC4801_final_project/REQUIREMENTS.md`，不实现 Optional 功能。

| 项目 | 对照需求后的判断与处理 |
|---|---|
| X-1 同雇主跨岗位预约 | **原测试预期错误**。FP-SCHED-2 的 “if and only if” 条件只要求时段属于申请岗位的雇主，不能增加岗位 ID 必须相同的限制。保留共享预约行为，把测试改成正常成功断言，并验证双方看到的预约仍属于原申请；SPEC 与界面明确“参考岗位”的含义。 |
| X-2 状态更新重定向 | 已修复。目标岗位来自服务端申请记录，表单 `job_id` 不再必填，也不能影响重定向。遗漏或篡改该字段均能回到正确申请人页面。 |
| X-3 登录状态下再次注册 | 已修复。GET/POST `/register` 在已登录时返回主页，不创建账号、不替换现有会话；退出后仍可正常注册。 |
| X-4 文本字段无业务长度上限 | **不是本轮强制需求缺陷**。规范未规定此类长度限制；原健壮性测试的有效结论是输入不能导致 500、SQL 注入或 XSS。没有为使测试通过而增加任意字段限制；生产环境的资源配额仍属后续加固。 |
| X-5 超大整数 ID 返回 500 | **属于 FP-AUTH-3 不符合项，现已修复**。SQL 绑定前检查 SQLite INTEGER 范围，缺失对象返回 404；覆盖岗位、申请、简历、时段及预约表单。仍先执行认证和角色检查，不用全局吞掉 OverflowError 的方式掩盖其他错误。 |
| X-6 状态下拉框无标签 | 已修复。每行状态控件具备独立 ID 和包含候选人名称的 aria-label；删除测试中的例外名单和 xfail。 |
| 额外发现：极端日期溢出 | 已修复。时区转换或计算结束时间溢出时返回 400，数据库没有新增时段；补充 FP-SCHED-1 单元测试和健壮性输入。 |
| 额外发现：状态校验先于属主校验 | 已修复。其他雇主提交非法状态也返回 403，不再因输入格式而提前返回 400；合法属主仍只能设置四种规定状态。 |

同时从申请人列表查询中移除未使用的私有简历字段。原有事务、唯一约束、
技能匹配公式、排序、删除冲突和预约状态保留规则均保持，并由相关测试复核。

测试分层仍保留：`tests/unit/` 是课程要求的验证入口，本次增加 7 个参数化展开后的
测试用例（总计 44 个），并将新增用例加入 README 的需求映射。其余测试作为额外证据，
不替代 FP-TEST-1。4 个旧 xfail 已全部移除，其中 1 个按规范纠正测试预期，
3 个修复对应实现；原先断言 500 的重复特征测试已删除。

修复前实测：`205 passed, 4 xfailed`。验证使用独立临时 SQLite 数据库；
Windows 沙箱无法访问 pytest 创建的临时目录，因此在沙箱外使用同一 Anaconda Python，
并指定仓库内 `.test-tmp/` 为隔离目录。该目录已从 Git 和 Docker 构建上下文排除。

修复后全部 **215 个用例通过，0 xfail**（其中课程单元测试 **44 个**）。为避免
重复执行已通过的测试，本轮分两组覆盖全套收集到的 215 个用例：

```text
python -m pytest tests/unit tests/system/test_known_gaps.py tests/accessibility tests/integration/test_cross_module_flows.py tests/robustness/test_malformed_input.py -q -p no:cacheprovider --basetemp=.test-tmp/fixes
# 149 passed

python -m pytest tests/config tests/performance tests/regression tests/system tests/integration --ignore=tests/system/test_known_gaps.py --ignore=tests/integration/test_cross_module_flows.py -q -p no:cacheprovider --basetemp=.test-tmp/remaining
# 66 passed
```

这里的 `python` 指已安装项目依赖的解释器（本机为 `D:\Anaconda\python.exe`）。
正常环境仍使用 README 中的 `python -m pytest tests/unit -q` 或
`python -m pytest tests -q`。`git diff --check` 同样通过。

部署验证边界：当前 Docker 客户端存在，但 Docker Desktop Linux engine 管道不存在，
因此本轮不能确认 Docker 构建/启动是否成功；也没有将本地修改提交或推送为最终评分 commit。
这些 FP-SUB-1 流程性条件需要在提交时另行验证，不能仅凭测试通过声称已完成。

### 修复后复核补充（2026-10-12 第二遍实测）

全树 215 用例通过后，对修复代码再做边界复探（会话通道、属性注入、id 位数阈值），结论：

| 项目 | 复核结论 |
|---|---|
| X-5 残留：≥4301 位数字的 URL 整数 id | **未完全覆盖，仍返回 500**。`object_id()` 覆盖了 2^63～约 4300 位十进制数的区间（→404），但 Python 3.11+ 对整数字符串转换设有 **4300 位上限**：URL 路径段 ≥4301 位数字时，Werkzeug `<int:...>` 转换器在**路由匹配阶段**的 `int(value)` 直接抛 `ValueError: Exceeds the limit (4300 digits)`，既不经 `object_id()`，也不是 `werkzeug.routing.ValidationError`（后者会优雅 404），最终 **500**。实测阈值：4300 位 → 404；4301 位 → 500。所有 `<int:...>` 路径（`/jobs/`、`/applications/`、`/candidates/<id>/resume` 等）同样暴露。**表单通道安全**：POST `/bookings` 等超长数字返回 400。严重性极低（无数据影响，仅畸形 URL 探测面），但属 X-5 同族的 FP-AUTH-3「缺失对象→404」残余。**建议**：注册自定义 int 转换器，把 `to_python` 的 `ValueError` 包装为 `werkzeug.routing.ValidationError`（路由不匹配 → 404），并在 `test_fp_auth_3_oversized_object_ids` 参数中加入 ≥4301 位的值。 |
| X-1 表述一致性 | 确认：SPEC「Availability is shared across all postings of the same employer…」段落、slots/application_detail 界面文案、`test_fp_sched_2_shared_employer_availability` 三处一致，且 FP-SCHED-2 iff 论证成立。 |
| X-2 / X-3 / X-6、极端日期、状态校验顺序 | 确认修复有效：篡改/缺失 `job_id` 均回到正确申请人页；已登录访问 `/register` 302 回主页且不建号；状态下拉有独立 id + 含候选人名的 aria-label；**属性注入实测被 Jinja 转义**（display_name 含 `"><script>` 在 aria-label 中安全）。 |
| `object_id` 覆盖面 | 确认：所有用户可控 id 入口（服务层查询/更新/删除/预订）均先过 `object_id`；其余绑定来自 DB 行或会话 id；`has_applied` 仅在 `get_job` 校验后调用；2^63-1（范围内不存在）→404，2^63 及负向越界 →404，认证/角色检查仍先于对象检查。 |

---

> 本文件按轮次记录审查/测试。**第三轮（2026-10-12）** 为测试补充审查，分两批：
> 第一批集成/系统测试，第二批回归、健壮性、性能、可访问性、配置测试（均见下）；
> 其后保留 2026-09-29 的第二轮历史记录（其问题均已修复，不再重复跟踪）。

---

# 第三轮：测试补充审查（2026-10-12）

- **审查对象**：本目录（Team_XYZ / TalentMatch，Flask + SQLite 实现）
- **审查依据**：`CSC4801_final_project/REQUIREMENTS.md`（强制 **MUST / MUST NOT**）
- **本轮方式**：编写多层级测试，以测试驱动方式排查实现问题；发现的问题记录在下文
  「本轮新发现的问题」。**`tests/unit/`（课程规定的 FP-TEST-1 学生单元测试）零改动**。
- **测试分层（与课程规定的单元测试严格区分）**：

| 层级 | 位置 | 命令 | 数量 | 性质 |
|---|---|---|---|---|
| 单元测试（**课程规定 FP-TEST-1，本轮未改动**） | `tests/unit/` | `python -m pytest tests/unit -q` | **37 passed** | 既有学生单元测试 |
| 集成测试 | `tests/integration/` | `python -m pytest tests/integration -q` | 22 passed + 1 xfail | 路由↔服务↔真实 SQLite schema、多线程竞态、跨模块一致性 |
| 系统测试 | `tests/system/` | `python -m pytest tests/system -q` | 24 passed + 1 xfail | 黑盒 HTTP（授权矩阵/多角色旅程/安全面/真实进程冒烟） |
| 回归测试 | `tests/regression/` | `python -m pytest tests/regression -q` | 11 passed | 历史 bug 修复的锁定测试（防止回潮） |
| 健壮性/模糊测试 | `tests/robustness/` | `python -m pytest tests/robustness -q` | 88 passed + 1 xfail | 畸形/敌意输入、Unicode、Cookie 篡改、事务回滚注入 |
| 性能/负载测试 | `tests/performance/` | `python -m pytest tests/performance -q` | 6 passed | 大数据集响应预算、吞吐、混合并发负载、查询量特征 |
| 可访问性测试 | `tests/accessibility/` | `python -m pytest tests/accessibility -q` | 7 passed + 1 xfail | 页面语言/标题/h1/表单 label/表头/按钮文本结构 |
| 配置/CLI/部署契约 | `tests/config/` | `python -m pytest tests/config -q` | 10 passed | manage.py 命令、env 变量、工厂隔离、WSGI 入口 |
| **全部** | `tests/` | `python -m pytest tests -q` | **205 passed + 4 xfailed** | |

  4 处 `xfail(strict=True)` 对应下文 **X-1 / X-2 / X-5 / X-6** 的复现测试（断言「正确行为」，
  修复后会以 XPASS 失败提示摘除标记）；每处另有一条「现状特征测试」记录当前行为。
  `tests/system/test_live_server_smoke.py` 按文档命令启动真实 waitress 进程（`manage.py init-db/seed/run`）
  并经 TCP 交互；需安装 `requirements.lock` 中的 `waitress==3.0.2`。

---

## 一、本轮覆盖说明

相比 `tests/unit/`（按 FP-TEST-1 对业务逻辑与代表性边界的单元断言），本轮新增测试专门覆盖
**只有把组件拼起来才暴露**的行为：

1. **数据库层兜底是否真实存在**（`tests/integration/test_db_integrity.py`）：
   绕过服务层直接对真实 schema 断言 `UNIQUE(job_id,candidate_id)`、`CHECK(status/role/时间)`、
   `bookings` 的两个 UNIQUE、以及 `ON DELETE RESTRICT`（裸 SQL 删除有依赖的 job/已订时段同样被拒）。
2. **FP-SCHED-3 的真实并发**（`tests/integration/test_concurrent_races.py`）：
   规范注明「单元测试 double 不能证明数据库并发行为」。本轮用 **Barrier 同步的真实双线程 + 独立连接**
   验证：同一时段两名合格候选人竞态 → **恰好一人成功**，败者 409 且消息为文档化的
   `Slot already booked`，库里恰好一行 bookings；同类竞态覆盖重复投递、重复注册、
   同申请双时段、以及「并发 apply ↔ delete job」无论交错如何都不会留下孤儿数据或 500。
3. **跨视图/跨模块一致性**（`tests/integration/test_cross_module_flows.py`）：
   候选人榜与雇主申请列表的分数必须来自同一实现（实测两边一致）、技能修改即时双向重算、
   预订在离开 `Interviewing` 后仍挂在申请上且时段保持不可用、平分排序的两级 tie-break。
4. **HTTP 层授权矩阵**（`tests/system/test_http_auth_matrix.py`）：
   全部受保护路由 × 匿名/错角色/属主/非属主 → 302/401/403/404 逐项断言（FP-AUTH-3 可观测契约），
   包括「未登录 POST 先 401 而不是被 CSRF 遮蔽」。
5. **多角色端到端旅程**（`tests/system/test_http_journeys.py`、`test_http_scheduling_flow.py`）：
   以「浏览器方式」（CSRF 从表单 HTML 抓取、cookie 会话、跟随业务跳转）走完注册→建档→建岗→
   建时段→双人投递→改状态→预订→双方可见→删时段/删岗位被拒的全链路；并逐条验证
   FP-SCHED-2 的资格条件在 HTTP 层的表现（状态非 Interviewing 不给 UI 且直发 409、
   已订时段从可订列表消失、文档化冲突消息、预订在状态变更后保持）。
6. **安全面端到端**（`tests/system/test_http_security_surface.py`）：
   XSS 载荷写入每一个用户可控字段（显示名/技能/简历/公司/岗位标题与描述）后，
   对所有会渲染它们的页面断言不可执行转义；SQL 元字符作为数据入库并可回读（表结构完好）；
   口令哈希不出现在任何响应；缺/伪 CSRF token → 403 且数据不被修改；
   所有 POST 表单都携带 `csrf_token` 字段；静态检查 services/routes 无字符串拼接 SQL。
7. **真实进程冒烟**（`tests/system/test_live_server_smoke.py`）：
   按 FP-DOC-1/FP-SUB-1 的文档路径执行 `manage.py init-db` / `seed` / `run`，对真实 TCP 端口完成
   演示账号登录、种子数据分数核对（FP-MATCH-1 示例行）、Interviewing + 可订时段核对、
   注册→登出→会话失效全流程。
8. **回归锁定**（`tests/regression/test_bugfix_lockins.py`）：把前两轮修复的每一个 bug
   （未登录 POST 被 CSRF 遮蔽、非 ASCII CSRF 500、过期时段误标 available、编辑页越权泄露、
   雇主申请详情 403、重复投递/注册 500、password_hash 出栈、删除事务性、FK 竞态 500、
   种子文案不一致）各钉一条 HTTP/服务层锁定测试，防止未来重构回潮。
9. **健壮性 / 模糊**（`tests/robustness/`）：17 类敌意载荷（空值/控制字符/50KB 长串/XSS/SQLi/
   SSTI 路径穿越/emoji/CJK/RTL 覆盖字符）灌入全部用户可控端点，断言永不 500；
   URL 畸形 id、非常规 HTTP 方法、JSON 误投；会话 Cookie 篡改与异密钥重放必须被拒；
   用 SQLite 触发器注入事务中段故障，验证 `create_job`/`update_job` 全量回滚无半截数据。
10. **性能 / 负载**（`tests/performance/`）：45 岗位 × 20 候选人 × 450 申请的数据集下，
    核心页面 3s 预算、50 连发 <15s、8 线程混合读写无 5xx；并用 trace 回调记录
    `list_jobs_with_scores` 的查询量增长特征（见观察项）。
11. **可访问性**（`tests/accessibility/`）：全部 15 个界面的 lang/charset、标题唯一非空、
    恰好一个 h1、表单控件 label 关联、表格 th、按钮文本（工具层 a11y 静态检查）。
12. **配置 / CLI / 部署契约**（`tests/config/`）：`manage.py` 三命令与 `--help`、
    `init-db` 幂等与嵌套目录创建、`seed` 可重复且形状符合 FP-DOC-3（5 用户/3 岗位/5 申请/3 时段）、
    DATABASE/PORT/SECRET_KEY 环境变量生效、无 SECRET_KEY 可启动（FP-SUB-1）、
    双 app 工厂数据库隔离、`run:app` WSGI 入口存在（Dockerfile CMD 依赖）。

---

## 二、本轮新发现的问题

> 均为 **低危及以下**，无 MUST / MUST NOT 级不满足项。每项附复现测试。

### X-1（低）｜同一雇主的「跨岗位」时段可被预约（实现内模型不自洽）

- **文件**：`app/services/scheduling.py::book_slot`、`list_available_slots`
- **功能**：FP-SCHED-2（预约资格）
- **描述**：时段在创建时绑定 `job_id`（`create_slot(employer_id, job_id, …)`，UI 也按岗位建时段），
  但 `book_slot` 只校验 `slot.employer_id == application 所属岗位的 employer_id`，
  **从不校验 `slot.job_id == application.job_id`**；候选人预约页 `list_available_slots(employer_id)`
  也按「雇主」而非「岗位」列出时段。结果：申请岗位 A 的候选人可以订走雇主为岗位 B 创建的时段。
- **对照规范**：FP-SCHED-2 的字面条件是「the slot belongs to the **employer** for the candidate's
  application」——按字面**不构成 MUST 违规**；但与「时段按岗位创建/展示」的实现模型不自洽，
  属产品逻辑缺口（面试安排会错位到错误的岗位）。
- **复现测试**：`tests/integration/test_cross_module_flows.py::test_cross_job_slot_booking_gap`
  （`xfail(strict=True)`：断言跨岗位预约应被拒绝，当前会成功）
- **建议**：在 `book_slot` 资格链中增加 `slot.job_id == application.job_id`，并让
  `list_available_slots` 按 `job_id` 过滤（或在 SPEC 中明示「时段可跨岗位共享」的产品语义）。

### X-2（低）｜`set_status` 成功后的重定向目标取自表单 `job_id`，可被篡改

- **文件**：`app/routes/employer.py::set_status`
- **功能**：FP-EMP-3（申请人管理）周边导航
- **描述**：路由把 POST 表单里的 `job_id` 仅用于重定向：`redirect(url_for("employer.applicants", job_id=job_id))`。
  状态变更本身以 `application_id` 为准并正确校验属主，但重定向可被指向**任意**（包括他人的）岗位：
  实测伪造 `job_id=2`（他人岗位）后状态成功改为 `Interviewing`，响应 302 → `/jobs/2/applicants`，
  跟随后落在 **403** 错误页（成功动作却看到失败页；flash「Application status updated.」还会串到
  下一个成功页面）。`job_id` 缺失时整个请求 400，但状态并未变更（尚可）。
- **对照规范**：非 MUST 违规（属主校验未被绕过），属导航正确性/体验缺陷。
- **复现测试**：`tests/system/test_known_gaps.py::test_status_change_redirects_to_the_applications_own_job`
  （`xfail(strict=True)`：断言重定向应回到申请所属岗位）；
  `test_tampered_job_id_currently_reaches_foreign_applicants_page`（现状特征，当前通过）。
- **建议**：重定向使用服务端已知的 `detail["job_id"]`（`set_status` 返回值已含该字段），
  表单 `job_id` 可完全删除。

### X-3（极低）｜已登录状态可直接 POST `/register` 静默切换账号

- **文件**：`app/routes/auth.py::register`
- **描述**：已登录用户提交注册表单会直接创建新账号并用 `_start_session` 覆盖会话（无登出/无确认）。
  走读与实测均确认无权限提升（只是切换到新账号自身），但属会话管理瑕疵：误触注册会「丢掉」当前登录态。
- **建议**（可选）：已登录访问 `/register` 时先重定向到首页，或注册前强制登出。

### X-4（极低）｜除简历外的文本字段无长度上限

- **文件**：`app/services/jobs.py`、`profiles.py`、`auth.py`（仅 `RESUME_MAX_LEN = 20000`）
- **描述**：实测 200KB 的岗位标题、超长显示名/公司名/技能串均可入库并正常渲染（400 校验只覆盖
  空值与简历长度）。非安全漏洞（全部参数化 + 自动转义），属健壮性/资源占用问题。
- **建议**（可选）：为 title/description/skills/display_name/company_name 增加合理长度校验。

### X-5（低）｜URL 中超出 SQLite INTEGER 范围的整数 id 触发 500

- **文件**：`app/services/jobs.py::_load_job` 等（`<int:...>` 路由转换器 → `WHERE id = ?` 绑定）
- **功能**：FP-AUTH-3 的 404 契约 / 健壮性
- **描述**：Werkzeug 的 `<int:...>` 转换器接受任意长度整数。访问 `/jobs/999999999999999999999`
  （已登录）时，Python 大整数绑定到 SQLite 抛 `OverflowError: Python int too large to convert
  to SQLite INTEGER`，未被任何错误处理器捕获 → **500**。对象不存在的正确表现应为 404。
  触发面：任何带 id 的 GET/POST 路由（jobs/applications/candidates/slots）。属健壮性缺陷
  （可被用来探测 500 响应，无数据影响）。
- **对照规范**：FP-AUTH-3 要求「missing object → 404」；超范围 id 属缺失对象的一种，
  以 500 响应不满足该契约的字面精神，但不涉及越权或数据破坏。
- **复现测试**：`tests/robustness/test_malformed_input.py::test_oversized_integer_id_is_404_not_500`
  （`xfail(strict=True)`）；`test_oversized_integer_id_currently_500s`（现状特征，当前通过）。
- **建议**：`<int(..., max=2**63 - 1)>` 限制转换器，或在 `app/errors.py` 增加
  `OverflowError → 404/400` 全局映射。

### X-6（低）｜申请人表的状态下拉框缺少 label/aria-label（可访问性）

- **文件**：`app/templates/employer/applicants.html`（`<select name="status">`）
- **功能**：可访问性（辅助技术可达性，非 MUST 项）
- **描述**：每行「Set status」的 `<select name="status">` 既无 `id`+`<label for=...>` 也无
  `aria-label`。屏幕阅读器只会播报「combobox」而无「申请状态」语义。同一表格的其他控件
  （表单按钮等）文本完整，其余 14 个界面的表单控件均已正确关联 label。
- **对照规范**：REQUIREMENTS.md 未设可访问性 MUST，不构成违规；作为质量项记录。
- **复现测试**：`tests/accessibility/test_page_structure.py::test_applicants_status_select_is_labelled`
  （`xfail(strict=True)`）；通用 label 检查已在 allow-list 中点名该控件。
- **建议**：给该 select 加 `aria-label="Application status"`（每行同名控件，用 aria-label 最简）。

### 观察（不计为问题）

- 同一岗位可创建**完全同时段**的多个 slot（无唯一/重叠约束）；规范未要求，记录备查。
- 槽位表单使用 `datetime-local` 控件，浏览器给出的是无时区值，页面已标注按 UTC 解释，
  与 `parse_iso` 的 naive→UTC 行为一致（实测带 `+08:00` 的输入会被正确折算为 UTC 存储）。
- **N+1 查询特征**：`list_jobs_with_scores` / `list_applicants` 对每个岗位/申请逐条查公司名与
  技能（O(N) 小查询）。在 45 岗位数据集下实测仍远低于性能预算（见
  `tests/performance/test_response_budgets.py::test_query_count_scales_linearly_not_quadratically`），
  属可接受的已知模式；若未来数据量上千可合并查询优化。
- Flask 对 OPTIONS 的自动响应是 200+Allow（标准行为），已在健壮性套件中单独断言。

---

## 三、本轮验证通过的区域（未再发现问题）

- **FP-SCHED-3 数据库原子性（规范要求「实现走查 + 运行系统」验证的项）**：
  真实双线程竞态 4 组场景全部符合契约（恰好一胜一负、败者 409 + `Slot already booked`、
  库内恰好一行、失败尝试零副作用可改订其他时段）。
- **FP-AUTH-3 / FP-SEC-1 可观测契约**：13 条路由 × 4 类调用方的完整矩阵全部命中预期
  302/401/403/404；对象 ID 扫描（改 ID 越权）在申请/简历/岗位/时段/预订五个域均被 403/404 拒绝。
- **安全面**：XSS（7 类字段 × 7 个渲染页面）、SQL 元字符（注册/档案/岗位）、口令哈希泄露、
  CSRF 缺失/伪造、表单 CSRF 字段完备性、字符串拼接 SQL 静态检查——全部通过。
- **一致性**：候选人/雇主两边 match 分数同源同值；技能改动双向即时生效；
  预订双方可见且在状态离开 `Interviewing` 后保留、时段保持不可用（FP-SCHED-2 尾注）。
- **数据层兜底**：UNIQUE / CHECK / RESTRICT 与服务层 409/404 映射行为一致（含裸 SQL 攻击面）。
- **种子与文档路径**：`manage.py seed` 输出含演示账号；真实进程冒烟确认 FP-MATCH-1 示例分数行
  （100/50/0 + 空技能 100）、四个状态、双 Interviewing 可竞态时段均在 UI 可见。
- **输入边界**：非整数 ID→400、过去时段/坏时间格式/未选岗位→400、超长简历→400、
  小写 role→400、GET 写端点→405、岗位技能为空允许——均符合文档。

---

## 四、结论

本轮以 **172 项新增测试**（集成 23 + 系统 25 + 回归 11 + 健壮性 89 + 性能 6 + 可访问性 8 +
配置 10；其中 4 项 xfail 为已知缺口的复现）覆盖了软件工程常规的多类测试：集成、系统、
回归、健壮性/模糊、性能/负载、可访问性、配置/部署契约。全树 `python -m pytest tests -q`：
**205 passed + 4 xfailed**（含 37 项课程单元测试）。

**未发现任何 MUST / MUST NOT 级不满足项。** 共发现 6 个轻微问题：

| # | 摘要 | 级别 | 建议 |
|---|---|---|---|
| X-1 | 跨岗位时段可被预约（实现内模型不自洽） | 低 | 建议修复（补 `slot.job_id` 校验） |
| X-2 | `set_status` 重定向目标取自表单可篡改 | 低 | 建议修复（用服务端 job_id） |
| X-3 | 已登录可静默 POST /register 切换账号 | 极低 | 可选 |
| X-4 | 除简历外字段无长度上限 | 极低 | 可选 |
| X-5 | 超大整数 URL id → 500（应 404） | 低 | 建议修复（限制 int 转换器或映射 OverflowError） |
| X-6 | 状态下拉框缺 label/aria-label | 低 | 建议修复（一行 aria-label） |

课程规定的学生单元测试套件（`tests/unit/`，37 项）本轮**零改动**，与新增测试相互独立：
`python -m pytest tests/unit -q` 仍为 FP-TEST-1 的提交命令。各层级测试均可单独运行（见分层表）。

---
---

# 历史记录：第二轮复查（2026-09-29，其问题均已修复）

> **2026-10-07 更新说明**：下文为 2026-09-29 的历史审查记录，不代表当前待办清单。
> 其中「新-1」「新-2」「新-4」已有代码修复，「新-3」的升级限制已在 INSTALL.md 中说明。
> 修复提交同时处理了未登录 POST 被 CSRF 检查遮蔽而返回 403 的问题，以及非 ASCII
> CSRF token 导致 500、雇主列表把过期时段标为 available 的问题；新增原始请求
> 和时段到期回归测试。SPEC.md 同步实际权限分层及响应优先级，INSTALL.md 更正
> Alice 的种子技能为 Python、SQL。

- **审查对象**：本目录（Team_XYZ / TalentMatch，Flask + SQLite 实现）
- **审查依据**：`CSC4801_final_project/REQUIREMENTS.md`（仅强制 **MUST / MUST NOT**；**MAY** 项不作要求）
- **复查范围**：修复提交 `d7d0eba`（相对首轮审查基线 `da647e3`，18 个文件 +293/−149）
- **复查方式**：逐文件 diff 走读 + 运行单元测试 + 全部原问题的运行时复验（Flask test client 实证）
- **复查日期**：2026-09-29

## 一、首轮问题复查结论：8 项全部解决 ✅

| # | 原问题 | 状态 | 修复方式与复验证据 |
|---|---|---|---|
| 1 | `GET /jobs/<id>/edit` 缺属主校验，越权泄露他人岗位（FP-EMP-2 / FP-AUTH-3 / FP-SEC-1） | ✅ 已解决 | `app/routes/employer.py::edit_job` 在渲染前调用 `jobs_service.get_owned_job()`（GET 与 POST 校验失败重渲染分支均覆盖）；`applicants` 路由同步加固。复验：外雇 GET 编辑页 → **403**，页面不含对方标题/描述 |
| 2 | 完整实现不在 `main` 分支（FP-SUB-1） | ✅ 已解决 | 修复提交已在 **`main`** 并推送至 `origin/main`。提交时仍须在课程平台提交**最终评分 commit** 的永久 URL（流程性事项） |
| 3 | `SPEC.md` 声称雇主可 GET `/applications/<id>` 但实现 403（FP-PROC-1） | ✅ 已解决 | 采用「改实现对齐 SPEC」：`application_detail` 改为 `@login_required`，候选人属主与雇主属主分流，模板以 `can_book` 隐藏雇主视图的预约 UI。复验：雇主属主 → **200**；外雇/其他候选人 → **403**；缺失 → **404**；未登录 GET → **302**、POST → **401** |
| 4 | 并发重复投递可能 500（FP-CAN-3 文档承诺 409） | ✅ 已解决 | `apply_to_job` 改为「直接 INSERT + 捕获 `IntegrityError` → 409」，以 `UNIQUE(job_id,candidate_id)` 作为竞态安全的重复检测 |
| 5 | `authenticate()` 返回含 `password_hash` 的整行（FP-AUTH-2 纵深） | ✅ 已解决 | 改为只取 `id, email, role` 返回（hash 不出模块） |
| 6 | `delete_job` / `delete_slot` 依赖检查不在事务内 | ✅ 已解决 | 检查与 DELETE 移入同一 `BEGIN IMMEDIATE` 事务；schema 依赖外键改为 **`ON DELETE RESTRICT`**，IntegrityError 映射 409 |
| 7 | FP-DOC-3「two jobs with required skills」解读风险 | ✅ 已解决 | `seed.py` 重排种子数据：两个**带技能**岗位 + Open Application（空技能）承载 FP-MATCH-1 示例 4；Alice 技能改为精确「Python, SQL」 |
| 8 | 种子文案与实际技能不一致 | ✅ 已解决 | 实际技能与 `manage.py` 输出、README、INSTALL、seed docstring 全部一致 |

## 二、第二轮问题（历史）：均已修复

### 新-1（低）｜`register_user` 并发重复注册仍可能 500 — ✅ 已修复
改为与 `apply_to_job` 相同的「INSERT + `IntegrityError` → 409」模式；第三轮的
`test_concurrent_duplicate_registrations_cannot_create_two_users` 以真实双线程复验通过。

### 新-2（低）｜非 UNIQUE 类 `IntegrityError` 的边缘竞态仍会 500 — ✅ 已修复
`translate_integrity_error` 现将 FOREIGN KEY 类错误映射 404（UNIQUE → 409），
并发 apply↔delete-job 竞态在第三轮 `test_concurrent_apply_and_delete_job_agree_on_outcome`
中验证：无论交错如何均得到干净的 409/404，无 500、无孤儿数据。

### 新-3（低）｜旧数据库不会自动获得 RESTRICT 外键，`init-db` 不迁移 schema — ✅ 已在 INSTALL.md 说明
升级说明已注明涉及 `app/db.py` 表结构变更时需重跑 `python manage.py seed`。

### 新-4（极低）｜雇主视图的「Back to applications」链接指向候选人专用页 — ✅ 已修复
`application_detail.html` 已按 `current_user.role` 分流返回链接（雇主 → applicants 页）。

## 三、第二轮结论（历史）

**首轮 3 个 MUST 级不满足与 5 个轻微问题全部修复**，剩余 4 个轻微项随后亦全部处理。
第二轮后无 MUST 级遗留；提交流程性待办（最终评分 commit URL）与干净环境 Docker 冒烟见第三轮结论。
