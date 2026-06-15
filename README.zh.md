# Spex — 规格驱动开发技能

Spex 是一个为项目引入规格驱动开发的技能（skill）。它可以保存带有进度跟踪的
规格文档，同时将规格存放在仓库之外——避免代码和规格文档成为两套事实来源。
用户可以自定义存储目录和提示词模板，以符合团队规范。

## 亮点

- **完整的规格生命周期** — 通过 `/spex` 命令即可创建、修改、应用、提交和归档
  规格文档。
- **长时间任务的执行框架** — 实现方案被规划为 JSON 步骤；每个步骤完成时创建
  提交并在 `todo.json` 中记录时间戳，支持暂停/恢复和进度可视化。
- **小批量提交** — 每个步骤的变更控制在约 200 行以内，必须提交后才能进入下一步，
  避免大提交，保持代码审查的可控性。
- **可定制模板** — 使用 Jinja2 模板生成规格文档、任务提示词和提交信息；
  支持按项目或全局覆盖。
- **灵活存储与分层配置** — 规格默认存放在仓库外（`~/.spex/`）；`.spex.toml`
  配置文件在项目、用户和系统三个层级加载，就近优先合并，`SPEX_CONFIG_FILE`
  环境变量可覆盖所有发现逻辑。每个层级可设置独立的 `spex_root` 控制存储位置。
- **分支管理** — 可选地为每个规格创建和切换 `spex/<name>` 分支，
  支持自动合并或创建 PR。
- **支持 worktree 和子模组** — 规格锚定到主 worktree，所有 worktree
  共享同一个规格存储；同时支持子模组。
- **模糊名称匹配** — 所有命令接受部分规格名称，支持交互式消歧。
- **钩子** — 可扩展的 `post-action` 钩子通过 stdin 接收 JSON 事件，
  适用于遥测、通知或自动创建 pull request。
- **CLI + 技能** — 在编程代理中使用 `/spex`，或使用独立的 `spex`
  CLI 查看、展示和管理规格。

## 用法

此技能需要手动调用——**不会**通过 LLM 自动触发。
通过 `/spex` 斜杠命令使用，有两种方式：

- **自由提示词** — 由 LLM 判断用户意图：

  ```
  /spex <自然语言提示词>
  ```

- **显式子命令** — 直接加载对应的技能模板：

  ```
  /spex <command> [arguments...]
  ```

### 技能命令

| 命令             | 别名               | 说明                          |
|-----------------|--------------------|------------------------------|
| `create`        | `new`              | 创建新的规格文档（不修改代码）    |
| `modify`        |                    | 修改规格的需求                 |
| `apply`         | `run`, `do`, `go`  | 应用规格生成代码                |
| `apply-one-step`| `step`             | 执行规格待办列表中的一个步骤      |
| `submit`        | `merge`            | 提交已完成的工作（合并或创建 PR） |
| `archive`       |                    | 归档已完成的规格                |
| `init`          |                    | 初始化 spex 环境               |

#### `/spex create <spec-name> [description]`

根据配置的模板创建新的规格文件，包含标准章节
（概述、需求、设计、实现备注）。

#### `/spex modify <spec-name>`

修改现有规格的需求。

#### `/spex apply <spec-name>`

应用规格驱动实现——将需求和设计转化为代码变更。

#### `/spex apply-one-step <spec-name>`

执行规格待办列表中的单个步骤后停止。

#### `/spex submit <spec-name>`

提交已完成的工作，根据 `submit_method` 配置选项合并分支或创建 pull request。

#### `/spex archive <spec-name>`

将规格标记为 `archived`，记录归档日期，并移入 `archived/` 子目录。

#### `/spex init`

初始化 spex 环境——创建配置文件、规格存储目录和默认模板。

### CLI 命令

在编程代理中运行 `/spex init` 会将独立的 `spex` CLI 安装到
`~/.local/bin`。CLI 提供无需 AI 代理即可运行的命令：

| 命令             | 说明                        |
|------------------|----------------------------|
| `spex list`      | 列出规格及状态和进度           |
| `spex show`      | 显示规格概要信息              |
| `spex open`      | 在系统文件浏览器中打开规格目录  |
| `spex config`    | 显示已解析的配置              |
| `spex archive`   | 归档已完成的规格              |
| `spex init`      | 初始化 spex 环境             |

#### `spex list`

列出所有规格，显示状态图标和进度比率：

- `spex list` — 紧凑视图：规格名称、状态和进度（如 `3/5`）。
- `spex list -v` — 增加规格描述。
- `spex list -vv` — 增加各步骤的完成状态列表。
- `spex list --all-projects` — 包含所有仓库的规格，不限于当前仓库。

#### `spex show <name>`

- `spex show <name>` — 显示完整的规格内容和结构化的待办详情。
- `spex show -l <name>` — 简要列表格式（状态、日期、分支、进度）。

## 配置

Spex 使用 `.spex.toml` 文件进行配置。首次运行时，会在用户主目录下
创建默认配置和规格目录：

- `~/.spex.toml` — 全局配置
- `~/.spex/` — 默认规格存储（包含 `specs/`、`archives/`、
  `templates/` 子目录）

### 配置文件发现

Spex 从 git 仓库根目录**向上**搜索 `.spex.toml`，直到文件系统根目录，
然后回退到 `~/.spex.toml`。当找到多个文件时，它们会被合并，最近的文件
具有最高优先级。使用 `spex config` 可以查看已解析的配置文件、设置和
规格存储目录：

```bash
spex config
```

要覆盖所有发现逻辑，可设置 `SPEX_CONFIG_FILE` 环境变量指定
显式路径：

```bash
export SPEX_CONFIG_FILE=/path/to/custom.toml
```

### 配置选项

所有选项位于 `[spex]` 段下：

```toml
[spex]
# 规格存储的根目录
# spex_root = ".spex"

# 为规格创建和管理分支
# branch_management = true

# 限制只能在此分支上创建规格
# main_branch_name = ""

# 完成工作的提交方式：merge 或 pr
# submit_method = "merge"
```

| 键                  | 类型   | 默认值     | 说明                                                 |
|---------------------|--------|------------|---------------------------------------------------|
| `spex_root`         | string | `".spex"`  | 规格存储目录（相对于 `.spex.toml` 所在位置，或绝对路径） |
| `branch_management` | bool   | `true`     | 自动为每个规格创建/切换分支                            |
| `main_branch_name`  | string | `""`       | 仅允许在此分支上创建规格（空 = 任意分支）               |
| `submit_method`     | string | `"merge"`  | 完成工作的提交方式：`merge` 或 `pr`                   |

### `spex_root` 的作用域

当 `.spex.toml` 设置了 `spex_root`，它管辖该文件所在目录
**及所有子目录**。这允许你在不同层级使用不同的规格根目录：

```
/home/alice/
├── .spex.toml              ← spex_root = ".spex"（全局默认）
├── .spex/                  ← 全局规格
└── projects/
    └── my-app/             ← git 仓库
        ├── .spex.toml      ← spex_root = "specifications"（项目级）
        └── specifications/ ← 项目本地规格
```

**常见配置方式：**

- **仅全局**（默认）：规格存储在 `~/.spex/`，所有项目共享。
- **按项目**：在仓库根目录创建 `.spex/` 目录将规格保存在项目旁，
  可选地添加 `.spex.toml` 覆盖默认设置。
- **CI/构建覆盖**：设置 `SPEX_CONFIG_FILE` 指向构建专用配置，
  绕过所有 `.spex.toml` 发现逻辑。

## 安装

通过 [skills.sh](https://www.skills.sh/) 安装（适用于 Claude Code）：

```bash
npm install -g skills@latest
npx skills add jiangxin/spex
```

或手动克隆仓库：

```bash
git clone https://github.com/jiangxin/spex ~/.agents/skills/spex

# 适用于 Claude Code
ln -s ~/.agents/skills/spex ~/.claude/skills/spex
```

## 开发

### 前置要求

- Python 3.11+
- Node.js（用于 markdownlint 和 husky）

### 环境搭建

```bash
make setup
```

此命令以可编辑模式安装 Python 开发依赖（ruff、pytest、pytest-cov），
创建 `package.json` 符号链接，并运行 `npm install` 设置
[husky](https://typicode.github.io/husky/) git 钩子。npm 配置文件
命名为 `package.dev.json`（通过符号链接为 `package.json`），
以避免与阿里巴巴内部技能发布平台冲突。这些工具用于质量保证——代码检查、
测试和提交前检查。

### 可用的 Make 目标

| 命令             | 说明                                   |
|------------------|---------------------------------------|
| `make setup`     | 创建 package.json 符号链接并安装依赖     |
| `make lint`      | 对 Python 文件运行 ruff 检查            |
| `make lint-md`   | 对 Markdown 文件运行 markdownlint      |
| `make format`    | 使用 ruff 自动格式化 Python 文件         |
| `make test`      | 运行 pytest 单元测试（快速层）           |
| `make test-all`  | 运行所有测试（包括慢速测试）              |
| `make check`     | 运行所有检查（lint + lint-md + test）   |
| `make check-all` | 运行所有检查（包括慢速测试）              |
| `make coverage`  | 运行测试并生成覆盖率报告                 |

### 提交前钩子

本项目使用 husky 在每次提交前强制执行质量检查：

- **pre-commit**：运行 `make check`（ruff lint、markdownlint、pytest）
  ——检查失败时阻止提交。
- **commit-msg**：为 AI 辅助的提交注入 co-developed-by 尾注。

这些钩子通过 `make setup` 自动安装。

## 许可证

MIT
