## 2026-07-06 全站深色主题一致性修复
- 当前根因不是单一变量缺失，而是全局 CSS 与页面内联样式仍在大量使用浅色写死值，导致 data-theme=dark 只能覆盖部分底层 token。
- RequirementsWorkspace.tsx 的本地 <style> 和导出预览、TestPointsMap.tsx 的 MindElixir 样式对象、styles.css 的表单/表格/弹窗/登录页背景，是这次最主要的失配入口。
# Findings

## 2026-06-12 鑽夌鐩存帴 AI 鐪熷疄鎵ц
- 褰撳墠琛岀骇 AI 鎸夐挳鍙兘鎵ц `promoted_case_id` 瀵瑰簲鐨勬寮?YAML锛涙湭杞寮忚崏绋挎病鏈?`test-cases/icm/*.yaml` 鏂囦欢锛宺unner 鏃犳硶鐩存帴瀹氫綅銆?- 鐩存帴鑷姩杞寮忎細缁曡繃 YAML 璐ㄩ噺闂ㄧ锛屽苟鍙兘姹℃煋姝ｅ紡 case 璧勪骇锛涙湰杞噰鐢ㄢ€滀复鏃舵墽琛岃崏绋?YAML鈥濇洿瀹夊叏銆?- 鍚庣画濡傛灉鑽夌杩愯 passed锛屽啀鐢辩敤鎴峰喅瀹氭槸鍚﹁浆姝ｅ紡鎴栧悎骞?observed asset锛屼繚鎸佲€滅湡瀹為€氳繃鍚庡啀娌夋穩鈥濈殑璧勪骇鍘熷垯銆?
## 2026-06-07 Runner 璁剧疆鎺ュ叆鎵ц閾捐矾
- 鍘?runner CLI 娌℃湁鍙€夊弬鏁帮紝worker 涔熸湭璇诲彇骞冲彴璁剧疆锛涚幇鍦ㄩ€氳繃鍏煎鍙傛暟鏂瑰紡鎺ュ叆锛屼笉褰卞搷鍘?VS Code 鍛戒护銆?- `browser_mode` 浠嶄綔涓洪〉闈㈢瓥鐣ヨ鏄庝繚鐣欙紝瀹為檯鎺у埗娴忚鍣ㄦ槸鍚︽棤鐣岄潰杩愯鐨勬槸 `headless`銆?- `browser_mode` 宸插崌绾т负 headless 鐨勫崟涓€璇箟鏉ユ簮锛岄伩鍏嶉〉闈笂鍑虹幇浜掔浉鐭涚浘鐨勬祻瑙堝櫒妯″紡涓?headless 鍕鹃€夈€?
## 2026-06-07 绯荤粺璁剧疆鐪熷疄鍖?- 褰撳墠 `settings` 鑿滃崟瀛樺湪浣嗕笉鍙烦杞紝App 涔熸病鏈夎缃〉銆?- AI 璁剧疆宸插湪闇€姹傚伐浣滃彴鍐呯湡瀹炲彲鐢紝閫傚悎鍦ㄧ郴缁熻缃腑澶嶇敤鍚屼竴濂楁帴鍙ｃ€?- Runner 涓庤祫浜х瓥鐣ラ噰鐢?SQLite 鎸佷箙鍖栵紝棣栫増鍏堜綔涓哄钩鍙伴厤缃腑蹇冧繚瀛樼瓥鐣ワ紱鎵ц閾捐矾鍚庣画鍙€愭璇诲彇杩欎簺閰嶇疆鐢熸晥銆?
## 2026-06-07 鎶ュ憡璇︽儏椤垫帴鍏?observed asset
- observed asset 灞炰簬杩愯璇佹嵁锛屾斁鍦ㄦ姤鍛婅鎯呴〉姣旀斁鍦ㄦ墽琛屼腑蹇冩垨鐢ㄤ緥宸ュ叿绠辨洿绗﹀悎鈥滃厛瀹℃煡璇佹嵁锛屽啀纭鍚堝苟鈥濈殑娴佺▼銆?- 褰撳墠鍓嶇鍚堝苟鎸夐挳鎸夋姤鍛婄姸鎬佹帶鍒讹紝鍚庣浠嶄繚鐣?passed run 纭牎楠岋紝閬垮厤鍓嶇缁曡繃瀵艰嚧璧勪骇姹℃煋銆?
## 2026-06-07 鍚庡彴鐪熷疄鎵ц鑷姩娌夋穩璧勪骇
- 鐜版湁鎵ц涓績宸叉槸鍚庡彴 worker 璋冪敤 Playwright runner锛屽叿澶囦笉褰卞搷鐢ㄦ埛鍓嶅彴 Chrome 鐨勫熀纭€銆?- 椋庨櫓鐐瑰湪浜庝笉鑳借 AI 鎴栧け璐ヨ繍琛岀洿鎺ユ薄鏌撴寮?`automation_asset`锛屽洜姝ゅ簲鍏堜繚瀛?`observed_asset`锛屽啀鐢?passed run 鍚堝苟銆?- 鍚堝苟绛栫暐閲囩敤淇濆畧妯″紡锛氬凡鏈夎涔夊寲璧勪骇涓嶈瑙傛祴鍣ㄧ殑閫氱敤 selector 瑕嗙洊锛屽彧琛ュ厖 `status/source/observed_at/evidence`锛涚己澶卞瓧娈垫墠鐢?observed asset 濉厖銆?
## 2026-06-06
- 褰撳墠鍚庣宸叉湁 `case_drafts` 琛紝浣嗙己灏戣崏绋垮垪琛ㄣ€佽鎯呫€佺紪杈戙€佽浆姝ｅ紡鐢ㄤ緥鎺ュ彛銆?- 褰撳墠 `POST /api/test-points/generate-cases` 鍙帴鏀?`test_point_ids`锛屼笉鏀寔妯℃澘鍜屾爣棰樸€?- 褰撳墠 `AIService.generate_cases` 鏄湰鍦拌鍒欐嫾鎺ワ紝鏈帴鍏ュ凡閰嶇疆鐨勫ぇ妯″瀷銆?- 褰撳墠鐢ㄤ緥宸ュ叿绠变粛浠ラ潤鎬?鍗婇潤鎬佸睍绀轰负涓伙紝娌℃湁璇诲彇 `case_drafts`銆?- 鏈淇濈暀鈥滆鍒欑敓鎴愨€濅綔涓烘湰鍦扮ǔ瀹氬叆鍙ｏ紝鍚屾椂鏂板鈥淎I 鐢熸垚鈥濅娇鐢ㄥ綋鍓嶆ā鍨嬮厤缃€?- 杞寮?case 閲囩敤鏄惧紡鍔ㄤ綔锛屼笖鐩爣 YAML 鏂囦欢瀛樺湪鏃舵嫆缁濊鐩栥€?- `codex-chrome-smoke` 褰撳墠涓嶆槸 Git 浠撳簱鐩綍锛宍git status` 鏃犳硶鐢ㄤ簬鍙樻洿妫€鏌ャ€?
## 2026-06-06 Dashboard 棣栭〉鐪熷疄鍖?- 褰撳墠 Dashboard 浠嶅紩鐢?`dashboardConsoleLines` 鍜?`testPoints` mock 鏁版嵁銆?- 鐜版湁鍓嶇 API 宸茶鐩栭椤垫墍闇€鐨勫ぇ閮ㄥ垎鏁版嵁锛屽彲浼樺厛鍦ㄥ墠绔仛鍚堬紝涓嶅繀鏂板鍚庣鎺ュ彛銆?- Dashboard 鐪熷疄鍖栨棤闇€鏂板鍚庣鎺ュ彛锛屼娇鐢ㄧ幇鏈?API 鑱氬悎鍗冲彲婊¤冻棣栫増鎬绘帶鍙伴渶姹傘€?- Dashboard 浠嶄繚鐣?`PageId` 绫诲瀷浠?mock 妯″潡瀵煎叆锛涜繖涓嶆槸灞曠ず mock 鏁版嵁锛屽悗缁彲鍗曠嫭鎶婂鑸被鍨嬭縼鍑?mock 鏂囦欢銆?
## 2026-06-06 瀵艰埅绫诲瀷杩佸嚭 mock
- `mock.ts` 鐩墠娣峰悎浜嗘壙杞戒骇鍝佸鑸父閲忓拰鍘熷瀷鍋囨暟鎹紝瀵艰嚧鏍稿績椤甸潰浠嶄笌 mock 鏂囦欢鑰﹀悎銆?- `PageId`銆乣navItems`銆乣flowSteps` 灞炰簬鐪熷疄浜у搧缁撴瀯锛屽簲杩佸嚭鍒扮嫭绔嬬被鍨嬪拰瀵艰埅甯搁噺鏂囦欢銆?- 杩佺Щ鍚?`mock.ts` 鍙繚鐣?legacy demo data锛屾牳蹇冮〉闈€佺粍浠跺拰 API 绫诲瀷鍧囦笉鍐嶅紩鐢ㄥ畠銆?
## 2026-06-06 鍒犻櫎 mock.ts
- `mock.ts` 鍒犻櫎鍓嶅凡纭闆跺紩鐢ㄣ€?- 褰撳墠鐪熷疄瀵艰埅甯搁噺浣嶄簬 `web-ui/src/data/navigation.ts`锛岄〉闈㈢被鍨嬩綅浜?`web-ui/src/types.ts`銆?
## 2026-06-06 AI 鎶ュ憡鍒嗘瀽鐪熷疄鍖?- 褰撳墠鎶ュ憡璇︽儏鐨?`analysis` 鏉ヨ嚜鏈湴瑙勫垯鍑芥暟锛屼笉浼氳皟鐢ㄥ凡閰嶇疆鐨勫ぇ妯″瀷銆?- 涓洪伩鍏嶆墦寮€鎶ュ憡鏃惰妯″瀷寤惰繜闃诲锛岀湡瀹?AI 鍒嗘瀽閫傚悎鍋氭垚鏄惧紡鎸夐挳瑙﹀彂銆?- GET 鎶ュ憡璇︽儏缁х画杩斿洖鏈湴蹇€熷垎鏋愶紝POST 鍒嗘瀽鎺ュ彛璐熻矗鐪熷疄 AI 璋冪敤锛岄伩鍏嶉〉闈㈤灞忚妯″瀷鑰楁椂闃诲銆?
## 2026-06-06 AI 鍒嗘瀽缁撴灉缂撳瓨鍏ュ簱
- 褰撳墠 `POST /api/reports/{run_id}/analyze` 姣忔閮戒細璋冪敤妯″瀷锛屽彲鑳介噸澶嶆秷鑰楁湰鍦?杩滅▼妯″瀷璧勬簮銆?- 缂撳瓨闇€瑕佺粦瀹?report hash 鍜?provider/model锛岄伩鍏嶆姤鍛婂彉鍖栨垨妯″瀷鍒囨崲鍚庡鐢ㄦ棫缁撹銆?- GET 鎶ュ憡璇︽儏鐜板湪鍙鍙栧凡鏈?AI 缂撳瓨锛涙病鏈夌紦瀛樻椂浠嶈繑鍥炴湰鍦拌鍒欏垎鏋愶紝淇濊瘉棣栧睆绋冲畾銆?
## 2026-06-06 鎶ュ憡鍒嗘瀽鍘嗗彶鐗堟湰涓庡己鍒堕噸鍒嗘瀽
- 鐜版湁 `report_analyses` 閫傚悎浣滀负鏈€鏂扮紦瀛橈紝浣?`unique(run_id, report_hash, provider, model)` 涓嶉€傚悎淇濆瓨澶氭鍘嗗彶鐗堟湰銆?- 搴旀柊澧炵嫭绔嬪巻鍙茶〃锛屼繚鐣欐渶鏂扮紦瀛樼殑蹇€熻鍙栬兘鍔涖€?- 寮哄埗閲嶆柊鍒嗘瀽浼氳烦杩囨渶鏂扮紦瀛橈紝璋冪敤妯″瀷鍚庡悓鏃舵洿鏂版渶鏂扮紦瀛樺苟杩藉姞鍘嗗彶鐗堟湰銆?
## 2026-06-06 YAML 鑽夌鏍煎紡鏍￠獙
- 褰撳墠杞寮?case 鍙浛鎹?id 骞跺啓鏂囦欢锛岀己灏?YAML 璇硶鍜屽叧閿瓧娈甸棬绂併€?- 鑽夌鐢熸垚閾捐矾鍙兘浜х敓绌?`automation_asset`锛岃浆姝ｅ紡鍓嶅簲鏄惧紡鎷︽埅骞舵彁绀鸿ˉ榻愩€?- 瑙勫垯鐢熸垚鐨?YAML 鑽夌榛樿 `automation_asset.operation_steps/selectors/assertions` 涓虹┖锛屽洜姝ょ幇鍦ㄤ細琚棬绂佹嫤鎴紝绗﹀悎鈥滃厛浜哄伐琛ラ綈娌夋穩璧勪骇锛屽啀杞寮忊€濈殑鐩爣銆?
## 2026-07-02 Agent 断言展示
- 现状问题不在前台渲染数量，而在后端步骤模型：_build_agent_steps() 直接把 Agent history 映射为步骤，导致 expected_results 被拆成额外卡片。
- 前台现有 ExecutionCenter.tsx 右侧智能探索结果卡片只有摘要字符串，没有预期 vs 实际 / 待校验 / 通过 / 未通过结构化字段。

## 2026-07-02 expected-result-binding
- `expected_results` ????????? `_clean_case_step_text`??? `1-2.` ???????????
- ???????????????? `expected_result / actual_result / expected_result_status`??????????

## 2026-07-02 23:45
- 待确认：智能探索结果卡片当前已改为 expected/actual 展示，需要回溯旧逻辑的真实数据来源，再决定更稳的判定链路。

## 2026-07-03 00:02
- 旧版智能探索结果来源：ExecutionCenter 直接展示步骤 summary；summary 由 api._build_agent_steps 基于 case step 文本、decision.reason、action_summary、execution.result 拼出。
- 当前方案观感不佳的根因：后端仍在输出自由文本 actual_result，缺少将 expected_results 解析为结构化断言并与页面观测事实做确定性比对的判定链。

## 2026-07-03 00:18
- 断言链当前已从自由文本摘要切到结构化裁决链，后续问题重点将转到断言覆盖率而不是展示层。
- detail_assert_passed 这类无可见文本但已成功断言的场景，现允许使用 decision.value 作为确定性证据源。


## 2026-07-03 00:36
- 这版已形成稳定链路：expected_results 解析为 assertion_checks，由后端求值器给出 queued/completed/failed，前端只负责展示，不再自行裁决。
- inished 但缺少可核验证据的断言会保留为 queued，避免把证据不足误判成通过。


## 2026-07-03 USRMGT 结论
- USRMGT_FUN_002 当前主链已稳定使用 admin 登录，旧的 test 账号误用不再是最新代码路径问题。
- USRMGT_FUN_001 失败主因不是登录，而是多账号流程的阶段规划丢失了用户行菜单与第二次导航，导致阶段 3 落入 generic fallback。
- user_row_menu 动作本身也缺少先 hover 行再取更多按钮的前置动作，这会放大 hover 菜单类场景的不稳定性。

## 2026-07-03
- 当前真实阻塞点已从 hover/更多 菜单切换为 /system/user-auth/server/{id} 页面内的设备绑定执行。

- 已将 user_device_binding 从标题邻近容器扫描改为直接锁定右侧最后一个设备表格 tbody 与最后一组分页，避免误扫左侧服务器表格或局部标题容器。

- 进一步确认失败根因：设备名提取从 test_data 串联溢出到下一行步骤号，生成了 DxI(2)
1 这样的伪设备名；已改为逐字段逐行提取。

## 2026-07-03
- 鏈疆鐩爣鏄彧姊崇悊鏅鸿兘鎺㈢储缁撴灉鐩稿叧浠ｇ爜锛屼笉鏀逛笟鍔￠€昏緫銆?
- 鏃ч€昏緫锛歘build_agent_steps 鐩存帴鎸?trace.history 閫愭潯鐢熸垚姝ラ锛孍xecutionCenter 鐨勨€滄櫤鑳芥帰绱㈢粨鏋溾€濆彧鏄剧ず selectedStep.summary銆?
- 鏂伴€昏緫锛歘build_agent_steps 鍥炲埌鍘熷 case steps 缁村害锛屽苟鎶?expected_results 缁戝畾鍒板搴旀楠わ紝鍙充晶缁撴灉鍗＄墖浼樺厛灞曠ず assertion_checks銆?
- 褰撳墠鏄庢樉椋庨櫓锛氭柊澧炴柇瑷€姹傚€间笌姝ｅ垯瑙勫垯瀛樺湪澶ч潰绉贡鐮佸父閲忥紝涓旀渶缁堣鍐充粛鏄熀浜?observation/AI fallback 鐨勫惎鍙戝紡瑙勫垯锛屼笉鏄弗鏍煎彲璇佹槑鐨勯〉闈㈡柇瑷€鎵ц鍣ㄣ€?

## 2026-07-03 USRMGT_FUN_001
- 最新成功运行 ui-ff92205f1562 的阶段 7 仅因 fallback finish 而标记 completed，没有以步骤级 expected_result 判定结果校验阶段。
- 该次运行的结果校验 observation 明确显示 ICM 页仍为 admin 且仅见 Test Server#203 / 0台，与 case 目标不一致。
- 设备绑定阶段使用 _run_user_device_binding，当前优先点行内开关/复选框，但尚未验证每次点击后是否真的形成选中态并保存。

## 2026-07-03 23:30:07 USRMGT_FUN_001 步骤4/5显示异常
- 最新 agent run trace 已显示整案 passed，阶段链全部 completed；若前台步骤4/5仍显示 failed，优先怀疑 run detail 或前台步骤状态映射失真，而非执行链本身失败。

## 2026-07-04 00:33:37 USRMGT_FUN_001 修复结论
- 步骤4失败的根因是 assertion evaluator 不识别 execution.result=user_device_bound，导致设备勾选成功却被误判。
- 步骤5失败的根因是 account_switch 把‘退出登录’与‘重新登录’压成单条 history，后续兜底断言错误使用了 #/icm 页面证据。

## 2026-07-04 USRMGT_FUN_001 步骤4/5误判根因
- 步骤4失败并非真实执行失败，而是 expected_results 先被降成 text_contains，且 queued/failed 兜底时拿错了后续页面证据；修正后改为直接识别 user_device_bound。
- 步骤5失败来自旧 trace 只有 account_switch_passed 合并记录，没有单独 logout 记录；已补历史兼容判定，新 trace 继续走拆分后的 logout/relogin 双记录。
- 步骤6失败来自‘登录成功’同时生成了 text_contains 兜底断言，聚合时被失败文本断言拖垮；已改为只保留 login_success 专用断言。


## 2026-07-07 内网访问放开
- 当前不能被内网访问不是单点问题，而是三处同时写死了环回地址：前台静态服务、浏览器里请求后端的 API 地址、后端允许的跨域来源。
- 仅改前台监听地址不够；如果不把 API 地址从 `127.0.0.1` 改成“当前访问主机”，外部用户打开页面后仍会请求自己的本机后端，页面会表现为无数据或报错。
- 最小可用方案已经足够：同机部署且前后端端口固定为 `5175/8000` 的前提下，不需要再引入反向代理或环境变量系统；直接按当前访问主机拼接 API 地址即可满足内网访问。

## 2026-07-07 非 ICM 项目入口放开
- `runner/browser.py::load_system()` 之前实际一直读取固定的 `systems/icm-internal.yaml`，`system_id` 参数只做了校验没有参与选文件，这会把任何外部项目都拉回 ICM 系统。
- `icm_platform/worker.py::_prepare_draft_case()` 之前对缺少 `system` 的草稿统一补 `icm-internal`，而像 `SEARCH_FUN_001` 这类 Bing 草稿本身只在 `requirements.project_id -> project_profiles.base_url` 上保存了目标站点。
- 因此要真正放开“非 ICM 项目”，必须同时修正“草稿落盘时的 system 推断”与“运行时 system yaml 读取/环境覆盖”这两层；只改其中一层都会继续回落到 ICM 登录页。

## 2026-07-07 SEARCH_FUN_001 外部站点执行阻塞
- 当前最新运行 `ui-99ef45c67e18` 并没有回退到 ICM 登录页；它已经正确落成 `external-template + https://bing.com`。
- 真实失败点是执行器把外部系统也当作“必须存在 login_state_check 的登录系统”处理，在 `ensure_logged_out() -> is_logged_in()` 里读取缺失键后直接抛 `KeyError`。
- 因此这次需要补的是“无登录态定义的外部系统兼容”，不是再次修改项目入口映射。
- 当前前台入口没有现成 favicon 资源；最小稳妥方案是直接补一份独立 `favicon.svg`，避免侵入页面主结构或依赖其它图片资源。
- 当前前台标签标题原本一处冗长、一处是 404 文案；统一收敛为 `QA Platform` 是最小且稳定的修复路径。
- 图标替换不需要再改入口 HTML；只要保留 `/favicon.svg` 路径稳定，后续改字母版或品牌版都只需替换单个静态资源。
- 当前用户实际访问的是 `web-ui` 主前台，不是 `frontend` 目录下那套静态页；因此只改 `frontend/index.html` 不会影响浏览器真实标签标题与图标。

## 2026-07-07 USRMGT_FUN_001 二次登录账号不一致
- 当前 `reports/draft-runs/ui-336e6a0972f2/case.yaml` 已明确写出：初次登录使用 `admin/Hubble_Service!1088`，后续切换账号时应使用 `test/123456`。
- 当前 `reports/agent-explore/ui-336e6a0972f2/trace.json` 已证实阶段1首次登录确实使用了 `admin`；问题不在首登，而在后续 account switch 链路。
- 最新成功运行 `reports/agent-explore/ui-a55173d601e7/trace.json` 已证实 account switch 阶段实际填写的是 `test/123456`，不是凭据解析错误。
- 真正失真点在 `runner/browser.py::current_logged_in_username()`：它原先先信 cookie subject，再看页头账号；当 cookie 已切到 `test`、但界面仍停留在 `admin` 头部时，会把“未真正切号”误判成登录成功。
- 因此最小修复不是改 case_login，也不是放宽步骤判断，而是把“当前登录账号”的裁决顺序改成“页头可见账号优先，cookie 仅做兜底”，这样 account switch 只有在界面真实切到目标账号后才会通过。
## 2026-07-08 智能探索步骤中间失败后最终通过
- 根因: Agent 运行中，断言求值器会基于当前 observation 立即得到 failed；但该 run 尚未终态，后续 history 可能提供命中证据并复算为 completed，所以前台出现“中间失败、最终通过”的状态闪烁。
- 修复边界: 只改变 active trace 的展示归并；执行动作报错、trace 最终失败、最终断言失败仍保留 failed。

## 2026-07-08 项目页顶部卡片与 AI 测试初始化骨架
- AI 测试初始化时的“先窄后宽”不是接口慢本身，而是详情区域在任务已选中但步骤数据未返回时退回了空态内容，导致最终三列工作区没有被稳定占位。
- 这类问题的最小修复路径是固定最终列结构并持续显示骨架，而不是在加载期切换不同布局。
- 项目管理顶部三卡与工作台视觉不一致的根因是没有直接复用 `qa-metric-card` 的结构语义，只是做了近似样式。

- 2026-07-08：AI 测试页的先窄后宽来自 isProcessInitializing 判断过早退出；把 selectedRun 的 live status 纳入判断后，可稳定维持最终三列骨架。
- 2026-07-08：项目页顶部卡片无需重写一套样式，直接复用工作台 qa-metric-card 即可获得同源高度、圆角、徽标和阴影。

## 2026-07-08 继续实际页面验证
- 待验证点：项目管理顶部统计卡是否复用工作台视觉；AI 测试页 live run 初始化时是否仍出现列宽跳变。

- 代码层确认：项目管理顶部统计卡已使用工作台同源 qa-metric-card 结构；AI 测试初始化条件已避免无步骤 live run 切换到窄空态。
- 风险：真实浏览器标签页未被控制接口枚举到，仍需用户当前浏览器刷新后肉眼确认或后续恢复浏览器连接再验。

## 2026-07-08 USRMGT_FUN_003 退出登录规划崩溃
- 根因：多账号流程只检查登录步骤总数和是否存在退出步骤，未要求退出之后存在第二次登录，导致打开登录页/首次登录/退出登录这类用例误入 account_switch 并在 next(second_login) 抛 StopIteration。
- 修复点：多账号判定改为 logout 后必须存在 login step。
- 验证：阶段规划器回归集 25 条通过，覆盖退出登录单账号路径，同时保留多账号切换路径。

## 2026-07-08 USRMGT_FUN_003 步骤2缺少截图
- 根因：规划器把步骤2“点击退出按钮”漏掉，直接把步骤3“点击确定”规划为弹窗处理；实际页面尚未弹出确认框，所以没有步骤2动作，也不会产生步骤2截图。
- 修复点：新增 `logout_prompt` 阶段负责点击退出入口并生成截图；后续 `dialog_form_fill` 负责确认弹窗的“确定”按钮。
- 验证：阶段规划器回归集 27 条通过，新增测试覆盖退出按钮阶段顺序与退出确认截图记录。
## 2026-07-09 WorkBuddy YAML/assertion 交接验证
- `runner/agent_explore.py` 的 `build_agent_goal()` 会读取 `automation_asset.assertions` 并写入 Agent Goal，因此 YAML 断言增强会进入智能探索提示词。
- 当前 working tree 存在大量非本交接改动；提交前必须只暂存交接相关 YAML/assertion + demo 文件，避免混入 UI、API、runner 历史改动。
- `TC-ICM-005` 的真实 trace 不能作为 ROI 通过证据：`runner/agent_explore.py` 在运行前固定 `ensure_logged_out()` + `open_login_page()`，而该 case 的前置条件是“已在登录后首页”；当前 YAML 没有登录账号数据，导致 agent 从登录页开始并把登录页误判为退出后的最终状态。
- 该问题属于用例前置条件与 agent-explore 启动策略不一致；在补齐“先登录再退出”的真实路径前，不应提交 WorkBuddy 的 assertion 增强为已验证有效。
- 补正后的 `TC-ICM-005` 已走真实路径：先以 admin 登录到 `#/index`，再打开退出入口、确认退出，最后通过 `#/login` 路由断言。
- `账号` / `密码` 属于 input placeholder，不适合作为 `detail_assert` 的文本信号；最终验证应优先使用 `#/login` 路由和登录控件 observation。
