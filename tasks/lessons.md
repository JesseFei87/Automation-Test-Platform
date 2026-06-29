# Lessons

- 2026-06-15: Project workflow requires reading `tasks/lessons.md` before repository analysis or code changes. Keep this file as the startup entry point and record new user corrections here before continuing future work.
- 2026-06-18: AI测试所有用户可见的步骤标题、步骤说明和 AI 执行说明必须中文化；后端返回英文时应在统一 view-model 层转换，不能散落到页面组件中。
- 2026-06-18: AI测试任务卡片中的执行时间与耗时保持左对齐，避免元信息在卡片中间形成不一致的视觉轴线。
- 2026-06-18: 任务卡片的时间行不仅要左对齐文字，还必须取消额外水平内边距，与上方用例标题严格共线。
- 2026-06-18: AI测试执行预览中的日志时间戳统一使用本地时间格式 `YYYY-MM-DD HH:mm:ss`，不直接展示 ISO 8601 原始值。
- 2026-06-18: AI测试左侧“执行入口”和“任务队列”共用固定 `400px` 栏宽，避免上下卡片宽度或视觉边界不一致。
- 2026-06-18: 顶部导航的 AI生成、AI测试、测试报告选中态必须分别继承工作台对应功能卡片的主色，保持跨页面视觉语义一致。
- 2026-06-18: 顶部导航按钮组必须在中间导航区域水平居中，不能因新增选中态样式偏向左侧。
- 2026-06-18: 用例管理查询区需要粘性固定在页面头部下方，方便滚动用例列表时继续调整筛选条件。

- 2026-06-18: 用例管理关键字搜索必须覆盖列表中实际显示的 YAML 用例ID；placeholder 文案必须与真实搜索范围保持一致。
