# 生产级 Agent 模块：边界情况与功能扩展学习清单

> 基于 OpenClaw 源码分析整理，用于指导 myclaw 项目开发

## 一、核心循环（基础）

```
用户消息 → 调用 LLM → 处理 tool_use → 执行工具 → 循环 → 返回文本
```

---

## 二、Context Window 管理

| 问题 | OpenClaw 的解决方案 | 文件 |
|------|---------------------|------|
| **Context Overflow** | 检测 overflow 错误，触发 compaction | `src/agents/pi-embedded-runner/run.ts:814-859` |
| **Tool Result 太大** | 单个 tool result 不超过 context 的 30%，超了就截断 | `src/agents/pi-embedded-runner/tool-result-truncation.ts` |
| **Session 压缩** | 当 context 满了，用 LLM 总结历史对话，压缩成摘要 | `src/agents/pi-embedded-runner/compact.ts` |
| **压缩超时保护** | 压缩操作最多 5 分钟，超时中断 | `src/agents/pi-embedded-runner/compaction-safety-timeout.ts` |
| **Context 最小阈值** | 低于 16K tokens 直接拒绝运行 | `src/agents/context-window-guard.ts` |

---

## 三、错误处理与重试

| 问题 | OpenClaw 的解决方案 | 文件 |
|------|---------------------|------|
| **API 调用失败** | 分类错误类型：auth/billing/rate_limit/timeout/format | `src/agents/failover-error.ts` |
| **重试次数限制** | 最大重试次数 `MAX_RUN_LOOP_ITERATIONS` | `src/agents/pi-embedded-runner/run.ts:679-706` |
| **认证失败** | 标记 profile 失败，cooldown 期间不再尝试 | `src/agents/auth-profiles.ts` |
| **Rate Limit** | 等待后重试，或切换到 fallback 模型 | `src/agents/model-fallback.ts` |
| **Timeout** | 区分用户中断 vs 网络超时，不同处理 | `src/agents/failover-error.ts:49-62` |

---

## 四、模型管理

| 功能 | OpenClaw 的实现 | 文件 |
|------|-----------------|------|
| **多模型支持** | 支持 Anthropic/OpenAI/Google/Ollama 等 | `src/agents/pi-embedded-runner/model.ts` |
| **模型 Fallback** | 主模型失败自动切换到备用模型 | `src/agents/model-fallback.ts` |
| **模型别名** | `sonnet` → `claude-sonnet-4-20250514` | `src/agents/model-selection.ts` |
| **API Key 轮换** | 多个 key 轮流使用，失败的 key 暂时禁用 | `src/agents/api-key-rotation.ts` |

---

## 五、Session 管理

| 功能 | OpenClaw 的实现 | 文件 |
|------|-----------------|------|
| **复杂消息存储** | 支持 text/tool_use/tool_result/image 等类型 | 外部库 `@mariozechner/pi-coding-agent` |
| **消息历史裁剪** | DM 限制历史轮数，避免过长 | `src/agents/pi-embedded-runner/history.ts` |
| **Session 修复** | 检测并修复损坏的 session 文件 | `src/agents/session-file-repair.ts` |
| **Tool 配对校验** | 确保每个 tool_use 都有对应的 tool_result | `src/agents/session-transcript-repair.ts` |
| **写锁** | 防止并发写入 session 文件 | `src/agents/session-write-lock.ts` |

---

## 六、工具系统

| 功能 | OpenClaw 的实现 | 文件 |
|------|-----------------|------|
| **工具权限** | 某些工具只有 owner 能用 | `src/agents/tools/common.ts:24` |
| **工具输入校验** | `ToolInputError` 处理参数错误 | `src/agents/tools/common.ts:26-33` |
| **工具结果格式化** | JSON 结果、文本结果、错误结果 | `src/agents/tools/common.ts` |
| **工具名白名单** | 只暴露允许的工具给 LLM | `src/agents/pi-embedded-runner/tool-name-allowlist.ts` |

---

## 七、System Prompt 管理

| 功能 | OpenClaw 的实现 | 文件 |
|------|-----------------|------|
| **动态 System Prompt** | 根据 channel、用户、时间等动态生成 | `src/agents/pi-embedded-runner/system-prompt.ts` |
| **System Prompt Override** | 支持运行时覆盖 system prompt | `src/agents/pi-embedded-runner/system-prompt.ts` |

---

## 八、高级特性

| 功能 | OpenClaw 的实现 | 文件 |
|------|-----------------|------|
| **Thinking Mode** | 支持 Claude 的 extended thinking | `src/agents/pi-embedded-runner/thinking.ts` |
| **流式输出** | 实时返回 AI 的回复，不等完整响应 | `src/agents/pi-embedded-runner/run/attempt.ts` |
| **子 Agent** | 支持 spawn 子 agent 处理复杂任务 | `src/agents/tools/subagents-tool.ts` |
| **Skills 系统** | 可扩展的技能模块 | `src/agents/skills/` |

---

## 学习优先级

### P0 - 必须有（基础可用）
- [ ] 1. 核心循环（Agentic Loop）
- [ ] 2. Session 支持复杂消息
- [ ] 3. 基础错误处理（API 错误捕获）

### P1 - 应该有（生产可用）
- [ ] 4. Tool result 截断（防止 context overflow）
- [ ] 5. 重试机制（带最大次数限制）
- [ ] 6. Session 历史裁剪

### P2 - 最好有（健壮性）
- [ ] 7. Session compaction（对话压缩）
- [ ] 8. 模型 fallback
- [ ] 9. 流式输出

### P3 - 锦上添花
- [ ] 10. Thinking mode
- [ ] 11. 子 Agent
- [ ] 12. Skills 系统

---

## 参考资源

- OpenClaw 源码：`/Users/liuxicheng/src/openclaw/`
- Anthropic API 文档：https://docs.anthropic.com/
- Claude Tool Use 文档：https://docs.anthropic.com/claude/docs/tool-use
