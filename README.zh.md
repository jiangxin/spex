# Spex — 规格驱动开发的 Skill 与命令行工具

## 什么是 Spex？

Spex，发音 /speks/，是一个 Coding Agent 的 skill 和命令行程序，帮助开发者使用 SDD（Spec-Driven Development，规格驱动开发）模式进行软件开发的完整生命周期管理。

它的核心目标是帮助你以规格驱动的方式进行开发——先定义要做什么（create），再一步步实现（apply），最后合并结果（merge）。

### 几个关键术语

- **SDD（Spec-Driven Development）**：规格驱动开发，核心理念是"先想清楚再做" —— 在 spec 文档中记录需求、设计决策和实施步骤，再动手写代码。
- **Spec（规格）**：一个功能或需求的完整设计产物，包含需求描述、技术方案和开发步骤。
- **Coding Agent**：AI 编程助手，可以用自然语言描述需求并自动生成代码。例如 Claude Code、Cursor、Windsurf、Cline 等。

### 全流程三步走

```bash
/spex create [需求]    →  创建规格文档（spec.md + todo.json）
/spex apply [spec]    →  按步骤逐步实现
/spex merge [spec]    →  合并完成的开发分支（自动归档）
```

---

## 5 分钟快速体验

假设你要给项目添加一个"用户登录"功能，以下是用 Spex 完成开发的完整流程。

### 第一步：创建规格

在 Coding Agent 中输入：

```bash
/spex create 添加用户登录功能，支持邮箱和密码登录，登录成功后返回 JWT token
```

Spex 会帮你生成三个文件：

- `spec.md` — 规格文档，包含需求分析、技术方案设计、文件变更计划。
- `todo.json` — 开发步骤列表，每个步骤包含步骤 ID、步骤名称和详细描述。
- `meta.json` — 规格元数据（原始提示词、规格名称、分支信息、作者身份等）。其中作者姓名和邮箱用于提交的作者标识。

用 `spex show` 可以查看刚刚生成的规格内容。

### 第二步：开发

在 Coding Agent 中输入：

```bash
/spex apply
```

Spex 会：

1. 自动创建一个 `spex/add-user-login` 的开发分支。
2. 按 `todo.json` 中的步骤逐一执行。
3. 每完成一个步骤，自动创建一个 git 提交。
4. 如果中途被打断（断网、Token 限流、需要切换任务），下次运行 `/spex apply` 时会自动从断点继续。

### 第三步：合并

在 Coding Agent 中输入：

```bash
/spex merge
```

Spex 会将已经完成的开发分支合并到主干，并归档该规格。

这就是 Spex 的核心流程：**create → apply → merge**。

---

## 安装

### 通过 skills.sh 安装

[skills.sh](https://www.skills.sh/) 提供 skill 的一键安装。使用 `skills` 命令行工具即可安装：

```bash
npx skills add jiangxin/spex
```

或者通过完整的仓库 URL：

```bash
npx skills add https://github.com/jiangxin/spex
```

当安装量达到一定数量后，spex 会被收录到 [skills.sh](https://www.skills.sh/)，届时可以直接搜索安装。

### 项目结构

安装完成后，skill 文件组织在 `skills/spex/` 目录下：

```
spex/
├── skills/
│   └── spex/
│       ├── SKILL.md          ← skill 入口文件
│       ├── commands/         ← 子命令
│       ├── scripts/          ← 可执行脚本
│       ├── templates/        ← 模板文件
│       └── references/       ← 参考文档
├── README.md
├── README.zh.md
├── pyproject.toml
├── tests/
└── ...
```

### 安装后初始化

打开 Coding Agent 工具，输入 `/spex init`。这将会：

1. 仅安装本 skill 在本地 skill 目录中声明的 Python 依赖（解析这些依赖时使用官方 PyPI）。
2. 创建 `~/.spex.toml` 配置文件。
3. 在 `~/.spex/` 目录下初始化规格存储目录。
4. 同步模板文件。
5. 将 spex 命令行工具安装（链接）到 `~/.local/bin/` 下。

---

## 使用 /spex 技能完成开发

在 Coding Agent 中，输入以 `/spex` 开头的命令来调用 spex 技能。

技能文件的 YAML front-matter 中定义了 spex 仅允许用户显式触发——大模型不会自行调用，对 Coding Agent 工具零影响。如下：

```yaml
---
name: spex
disable-model-invocation: true
... ...
---
```

### 主要命令

- **`/spex create [需求]`** - 将你的需求转换为 spec 文档。Spex 会分析需求，生成 `spec.md`（规格文档）和 `todo.json`（开发步骤列表）。创建完成后可以用 `spex show` 查看。

- **`/spex modify [spec-name] [变更]`** - 修改已创建的 spec。更新 `todo.json` 开发步骤，保留已完成步骤，重新生成未完成的任务。

- **`/spex apply [spec-name]`** - 开始按步骤实施开发。默认创建以 `spex/` 为前缀的本地分支。开发过程中可以用 `spex list` 命令行查看进度。

- **`/spex apply-one-step [spec-name]`** - 与 `/spex apply` 相同，但每次只执行一个步骤。适合需要逐步精细控制的场景。

- **`/spex merge [spec-name]`** - 将开发完成的 spec 合并到主干分支，并自动归档。

---

## 使用 spex 命令行

Skill 安装完毕后，在 Coding Agent 中执行 `/spex init` 即可完成配置、安装 Python 依赖，以及将 CLI 符号链接到 `~/.local/bin/`——确保该路径在 PATH 中。

**注意**：spex 命令行工具依赖 Python 3.9+，请确保系统中已安装。

### spex init

除了执行与 `/spex init` 技能命令相同的设置之外，还支持以路径为参数，在指定仓库的根目录下创建 `.spex.toml` 和本地 `.spex/` 目录。

依赖安装仅使用本 skill 的 `pyproject.toml`：本地 skill 目录加上官方 PyPI（仅 `pypi.org` / `files.pythonhosted.org` 的 https）。不会拉取或执行任意远程脚本。

### spex config

显示 spex 配置，包括 Git 信息、路径、配置文件列表和 spex roots。

```
── Git ───────────────────────────────────────────
  branch     = master
  remote_url =
  user_name  = Jiang Xin
  user_email = zhiyou.jx@alibaba-inc.com

── Paths ─────────────────────────────────────────
  cwd           = /Users/jiangxin/work/ai-native/spex
  top_workdir   = /Users/jiangxin/work/ai-native/spex
  main_worktree = /Users/jiangxin/work/ai-native/spex
  spex_root     = /Users/jiangxin/work/.spex

── Config ────────────────────────────────────────
  spex_root         = .spex
  branch_management = true
  main_branch_name  =
  submit_method     = merge

── Config Files ──────────────────────────────────
  /Users/jiangxin/work/ai-native/spex/.spex.toml
  /Users/jiangxin/.spex.toml

── Spex Roots ────────────────────────────────────
  /Users/jiangxin/work/.spex
  /Users/jiangxin/.spex
```

配置文件和 spex root 目录可以有多个，按优先级从高到低排列。优先级高的配置可以覆盖低优先级的配置值，高优先级目录中的模板和 hooks 也会覆盖低优先级目录中的同名文件。

### spex list

显示开发中的 spec 列表。在仓库中执行时显示本仓库关联的 specs，在仓库外或使用 `--all-projects` 时显示所有项目的 specs。

```bash
spex list                    # 当前仓库的 specs
spex list -v                 # 增加规格描述
spex list -vv                # 增加各步骤完成状态详情
spex list --archives         # 已归档的 specs
spex list --all-projects     # 所有项目的 specs
spex list --json             # JSON 格式输出
```

### spex show

显示给定 spec 的详细需求设计和开发步骤规划。

```bash
spex show [spec-name]
```

当 stdout 是 TTY 时，`spex show` 会把 `$PAGER` 作为 argv 启动（默认 `less -R`），而不是通过 `/bin/sh -c`。设置 `PAGER=cat` 可关闭分页。`PAGER` 中的 shell 元字符不会被解释。

### spex open

打开某个 spec 目录，或者在没有选择具体 spec 时，打开 spex_root 目录。

```bash
spex open [spec-name]
spex open [spec-name] --run "ls -la"
```

`--run COMMAND` 在 spec 目录中以 argv 执行 `COMMAND`，而不是通过 `/bin/sh -c`。管道和 `&&` 不会隐式生效；需要 shell 时请使用 `sh -c '...'`。

### spex archive

归档开发完成的 spec。

### spex merge

合并 spec 到主干并归档。功能和 `/spex merge` 技能命令相同。

---

## 为什么选择 Spex？

在 Spex 之前，社区已经有了不少规格驱动开发的工具，如 OpenSpec 和 spec-kit。那为什么还要再造一个？因为在实践中采用 SDD 范式时，会暴露出现有工具未能解决的痛点。

### 1. 长程任务中断恢复

一个复杂的需求开发，可能需要数十个开发步骤。执行中断的情况很多：断网、Token 限流、Agent 上下文溢出等等。你需要能够随时终止，并在断点处继续。

Spex 本身使用 SDD 模式开发，下面的输出是使用 `spex list --archives` 命令显示已归档的 specs。可以看出一些需求的开发步骤达到甚至超过 10 个：

```
📦   (8/8) 2026-06-16-17-16-improve-test-coverage  Improve test coverage by a...
📦 (10/10) 2026-06-15-11-47-rename-topic-to-spec   Normalize terminology: ren...
📦   (4/4) 2026-06-15-17-45-support-unborn-branch  Support unborn branch stat...
```

其中 `(10/10)` 表示共 10 个步骤，全部完成。Spex 把每一步的进度记录在 `todo.json` 中，随时可以暂停、恢复。

正如 Anthropic 的博客（[Effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)）指出的那样，相比 Markdown，大模型不太容易对 JSON 文件进行不当的修改或覆盖，因此 JSON 是跟踪开发步骤更好的格式。但随之出现了新问题：大模型直接修改 `todo.json` 时，倾向于将步骤描述压缩为简短的单行摘要，而非提供必要的多行 Markdown 上下文，导致细节缺失和代码生成不稳定。

开发过程中尝试了其他格式的中间文件，例如 XML 格式，虽然可以生成多行 Markdown 文本作为步骤描述，但 XML 中的字符转码增加了复杂度。最终的方案是开发了 `spex todo-helper` 助手程序，在为 `todo.json` 添加新步骤时使用 heredoc 方式提供多行的详细开发步骤。例如大模型使用如下命令行调用向 `todo.json` 中添加执行步骤：

```bash
$ spex todo-helper --name $spec_name append \
  --id step-1 --step-name "Short description" --details-from-stdin <<'DETAILS'
Markdown-formatted description of what this step does,
including file changes, logic, and acceptance criteria.

- Create `src/auth.py` with login endpoint
- Add input validation for email and password
- Write unit tests in `tests/test_auth.py`

**Acceptance criteria**: all tests pass, endpoint returns JWT
DETAILS
```

### 2. 原子化提交：小步快跑

Small batches（将功能拆分为多个小的开发步骤）是高质量开发的基石。这不是形式主义，而是开源实践和 DevOps 研究共同验证的成熟经验：

- 笔者在 [Git 项目](https://github.com/git/git)中贡献代码超过 10 年，深受社区严格代码评审规范的影响。共识是：每个提交只改一件事，保持在 100 行以内。
- [DORA 2025 年报告](https://dora.dev/research/2025/)发现：引入 Coding Agent 后，开发者倾向于让 AI 一次性生成大量改动，放弃了小批量实践。结果是编码速度提高了，但软件交付的整体效率反而下降。

对比两种开发过程（同样 1500 行代码更改）：

| | 好的开发过程 | 糟糕的开发过程 |
|---|---|---|
| 提交数量 | 20 个提交，每个不超过 100 行 | 1 个提交，1500 行代码 |
| 提交说明示例 | refactor: extract password validator<br>refactor: decouple user auth from session<br>feat: add email login endpoint<br>…… | 完成用户登录功能 |
| 评审时间 | 重构提交 2 分钟审完，逻辑提交逐个审查 | 评审人看了半小时还没理清逻辑 |

使用 Coding Agent 时，大模型很难自觉遵循"每步一提交"的实践。即使明确要求，它们仍然倾向于生成一个包含成百上千行更改的大提交。

Spex 的解法是记录开发步骤的 `todo.json` 中，每个开发步骤包含两个必填字段 `completed_at`（完成时间）和 `commit_title`（提交说明标题），只有在创建 Git 提交之后，才能将提交标题回填到 `commit_title` 字段，标记开发步骤已经完成。文件 `todo.json` 的内容示例如下：

```json
[
  {
    "id": "step-1",
    "name": "Update SKILL.md command routing and tables",
    "details": "Update SKILL.md to make `merge` the primary command...",
    "completed_at": "2026-06-17T12:08:42+08:00",
    "commit_title": "fae3c7c: docs: make merge the primary command..."
  }
]
```

### 3. 持续修改

需求会变，大模型也可能在需求分析中跑偏，需要人工纠正。对于已经生成或部分完成的 spec，Spex 支持迭代修改（`/spex modify`）。每次修改会更新 `spec.md` 的设计文档，同时保留 `todo.json` 中已完成的步骤，只重新生成未完成的部分。

### 4. 模板定制

每个团队都有自己的规范：spec 文档的格式、提交说明的风格、代码评审的 checklist 等等。Spex 支持自定义模板——使用 Jinja2 模板引擎渲染的 Markdown 文件。例如，`templates/apply-commit.md` 中的以下片段展示了 `user_name` 和 `user_email` 变量如何控制 git commit 命令：提供这些变量时，`-c` 参数会将提交作者设置为 spec 中指定的身份。

```markdown
{% if user_name and user_email -%}
- Use HereDoc to pass the commit message, and set the author identity
  to `{{ user_name }} <{{ user_email }}>`:

      git -c user.name="{{ user_name }}" \
          -c user.email="{{ user_email }}" \
          commit -F- <<'EOF'
      <commit message>
      EOF
{% else -%}
- Use HereDoc to pass the commit message:

      git commit -F- <<'EOF'
      <commit message>
      EOF
{% endif -%}
```

模板文件位于 `templates/` 目录下：

| 模板文件 | 用途 |
|---|---|
| `spec-template.md` | Spec 文档模板 |
| `modify-spec.md` | 修改现存 spec 的提示词模板 |
| `modify-todo.md` | 修改 `todo.json` 的提示词模板 |
| `apply-one-task.md` | 聚合 spec 和当前开发任务的提示词模板 |
| `apply-commit.md` | 生成提交的提示词模板 |

你可以在 `~/.spex/templates/` 下创建替换模板，覆盖内置模板。

### 5. 多项目支持

如果你在多个项目中使用 Spex，可以将不同项目的 spec 统一放在同一个 `spex_root` 目录下。每个 spec 的 `meta.json` 记录其归属项目。多项目的 spec 共池开启了一种强大的工作模式：一个 Coding Agent 可以从 spec 池中自主选择 spec，进入对应的工作区进行异步开发。多个 Coding Agent 甚至可以同时并行处理不同项目的 spec。

### 6. 分支管理

同时开发多个需求时，分支管理是个头疼的问题。Spex 默认自动处理：每个 spec 自动创建以 `spex/` 为前缀的独立开发分支，合并时自动归档。同时为分支添加描述（通过 `git config branch.<name>.description`），使合并提交说明中包含需求概述。

Spex 本身即使用 spex skill 开发。以下 `git log --merges` 输出展示了分支描述在合并提交中的呈现方式：

```
59c5929 Merge branch 'spex/merge-as-primary-command'
  * spex/merge-as-primary-command:
  : Make merge the primary command with submit as its alias, updating
  : CLI routing, help text, and documentation
  docs: update READMEs to make merge the primary command
  docs: rename commands/submit.md to commands/merge.md
  docs: make merge the primary command with submit as alias in SKILL.md
```

其中 `:` 开头的行是分支描述，来自 spec 的需求概述。

---

## 更多使用场景

### 将 spec 保存在仓库中

默认情况下 Spex 将 spec 保存在仓库之外（`~/.spex/`）。这样做是因为 spec 会随着开发完成而过时，**代码才是唯一事实**。
传统的工程实践要求写好提交说明，将修改原因（需求）和设计方案写在提交说明中，记录每个代码快照背后的设计考量。
大模型可以通过 `git blame` 追溯任意一行代码到其原始提交，理解每次修改背后的设计考量。

但是，如果你仍然想把 spec 放在仓库里，spex 也支持。你可以在仓库根目录下创建 `.spex.toml` 文件，设置 `spex_root`：

```toml
[spex]
spex_root = ".spex"
```

然后执行 `spex init .`（`.` 指代当前路径），即可在仓库中创建 `.spex` 目录保存生成的规格文档。

**说明**：创建的 `.spex` 目录下包含 `.gitignore` 文件，默认忽略 spec 文件，只将 templates 等文件保存到仓库。

### 平台集成：统一管理多仓库的 Spec

将 Spex 集成到开发平台时，通常需要统一管理多个代码仓库的 spec 生成和执行，而不是让每个仓库各自配置。Spex 支持通过环境变量 `SPEX_CONFIG_FILE` 指定配置文件，跳过仓库中的 `.spex.toml`：

```bash
export SPEX_CONFIG_FILE=/path/to/platform-spex.toml
```

这样平台可以统一控制 `spex_root` 位置、模板和 hook，确保所有仓库的 spec 集中存储和统一管理。

### 定制 spex 模板

用 `spex config` 查看 `spex_roots` 路径列表，选择一个模板目录（例如 `~/.spex/templates/`），创建替换的模板文件。可以从 `templates/examples/` 复制模板作为起点。

### 定制 hook

Spex 支持 pre-action 和 post-action 两种 hook。它们是项目本地的，语义等同于 git hooks：Spex 执行的是 spex_root 中用户提供的脚本，而不是远程代码。

- **pre-action** — 操作执行前触发。返回非零退出码时终止执行，可用于权限检查、环境验证。
- **post-action** — 操作执行后触发。即使失败也不影响已完成的操作，适合通知、遥测、和三方平台同步等。

以下操作会触发 hook：

| 操作 | 事件类型 | pre-action | post-action |
|---|---|---|---|
| `/spex create` | create | 创建 spec 目录后、设计内容前 | 创建完成后 |
| `/spex modify` | modify | 修改 spec 内容前 | 修改完成后 |
| `/spex apply` | apply | 开发步骤执行前 | 所有步骤完成后 |
| `/spex merge` | merge | 合并执行前 | 合并完成后 |

每个 hook 通过 stdin 接收 JSON 格式的事件数据。hook 脚本必须：

- 位于某个 spex_root 下的 `hooks/` 目录中（文件名即为 hook 类型，例如 `pre-action` 或 `post-action`）
- 具有可执行权限
- 不得是解析到该 `hooks/` 目录之外的符号链接
- 不得对其他用户可写（world-writable）

不安全的 hook 会被跳过（视为不存在）并记录警告。

---

## 常见问题

### Python 版本要求

Spex 的命令行工具依赖 Python 3.9+。可以用 `python3 --version` 检查。macOS 用户可以通过 `brew install python` 安装。

### spex 命令找不到

检查 `~/.local/bin/` 是否在 PATH 中：

```bash
echo $PATH
```

如果没有，在 `~/.zshrc` 或 `~/.bashrc` 中添加：

```bash
export PATH="$HOME/.local/bin:$PATH"
```

然后重新加载配置：`source ~/.zshrc`。

### spec 创建失败怎么办

运行 `spex config` 检查配置。确认 `spex_root` 路径存在且可写。

### 分支冲突如何处理

如果 `/spex apply` 时发现分支名冲突，说明同名的 spec 分支已经存在。你可以：

1. 用 `spex show` 查看该 spec 的当前状态。
2. 用 `/spex apply` 继续开发。
3. 如果不需要旧分支，可以先用 `git branch -D <branch-name>` 删除。

### 如何中断和恢复开发

- **中断**：直接停止 `/spex apply` 即可，进度已保存在 `todo.json` 中。
- **恢复**：再次运行 `/spex apply`，Spex 会自动找到第一个未完成的步骤继续。
- **查看进度**：`spex list [spec-name]` 查看已完成的步骤数。

---

## 关于 spex 的开发

- **仓库地址**：[https://github.com/jiangxin/spex](https://github.com/jiangxin/spex)
- `SKILL.md` 是一个路由文件，逻辑拆解到 `commands/*.md` 中。
- 模板文件在 `templates/*.md` 下。
- 脚本在 `skills/spex/scripts/` 目录下，使用 Python 3.9+ 编写。
- 运行测试：`make test`（快速），`make test-all`（全部，包含慢测试）。
