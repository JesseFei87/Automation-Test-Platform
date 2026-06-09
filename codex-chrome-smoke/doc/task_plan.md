# Task Plan: 用例生成链路增强

## Goal
把“测试点思维导图选中节点后生成 YAML”升级为可追溯的用例草稿闭环：
选点确认、模板选择、生成 YAML 草稿、用例工具箱管理、人工确认后转正式 case 文件。

## Target
- 后端提供 case draft 列表、详情、编辑、转正式 case 能力。
- 测试点生成 YAML 支持模板、标题和 AI 设置。
- 前端测试点页增加生成配置面板。
- 前端用例工具箱读取真实草稿并支持编辑、预览、转正式 case。

## Safety
- 不自动写入正式 `test-cases/icm/*.yaml`。
- 转正式 case 必须显式输入 case id 和文件名。
- 不覆盖已有正式 case 文件。

## Dashboard Real Data Goal
- 首页改为读取真实 API 数据，不再展示 mock 统计。
- 保持原有布局和导航方式。
- 后端不可用时显示清晰错误，不白屏、不伪造数据。
