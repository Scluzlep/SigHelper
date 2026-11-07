# android-sig / SigHelper

一个用于管理 Android APK 签名的命令行工具：**生成与复用 PKCS#12 签名密钥、迁移旧密钥目录、校验证书及 APK、同步 GitHub Actions Secrets**。

- 默认将所有签名材料保存在 `/root/android-signing/`，**不会提交私钥或密码到 Git 仓库**。
- Python 3.9+ 标准库实现，无需 `pip install`；系统命令依赖见下文。
- 安全优先：不重建已有密钥、保留历史 Alias、仓库绑定、目录锁、原子生成和文件权限检查。
- 不修改目标仓库的 GitHub Actions 工作流；只负责准备签名材料及校验。

> **重要：** GitHub Secrets 不能被读取还原。本工具无法从 Secrets 恢复私钥。请在 VPS 之外**单独加密备份** `.p12` 和密码文件；同一 APK 的后续版本应继续使用同一签名证书。

## 安装

适用 Linux（使用 `fcntl.flock` 文件锁）。需要 Python 3.9+、JDK 的 `keytool`、OpenSSL。涉及 GitHub 时还需要已完成认证、对目标仓库有 Secrets 写权限的 [GitHub CLI (`gh`)](https://cli.github.com/)；验证 APK 时需要 Android SDK Build Tools 的 `apksigner` 在 `PATH` 中。

Ubuntu / Debian 可先安装基础依赖：

```bash
sudo apt-get update
sudo apt-get install -y python3 default-jdk-headless openssl git
# 另行安装并登录 GitHub CLI (gh)：gh auth login
# 如需验证 APK，安装 Android SDK Build Tools 并确保 apksigner 在 PATH 中。
```

安装工具：

```bash
git clone https://github.com/OWNER/SigHelper.git
cd SigHelper
sudo install -m 0755 android-sig /usr/local/bin/android-sig
android-sig help
```

默认目录在 `/root`，通常需要 root 权限运行：

```bash
sudo android-sig list
```

**注意：** 如果用普通用户执行 `gh auth login`，`sudo` 切换成 root 后，root 未必拥有 GitHub 登录状态。可以给 root 单独执行 `sudo gh auth login`，或者在安全的权限条件下正确配置 root 可访问的 `GH_CONFIG_DIR` / `GH_TOKEN`。不要在命令行明文写出 token。

开发和测试时可以覆盖根目录，不修改默认值：

```bash
ANDROID_SIG_HOME="$HOME/android-signing" android-sig list
```

## 完整命令

```text
android-sig help [gen|adopt|sync|veri|list]
android-sig gen <owner/repo> [local-name] [--local-only] [--replace-secrets]
android-sig adopt <owner/repo> [local-name] [--alias ALIAS] [--sync]
android-sig sync <owner/repo> [local-name]
android-sig veri [owner/repo] [local-name] [--apk FILE.apk] [--remote] [--json]
android-sig list [--json] [--verbose]
```

任意子命令都有单独的 `--help`，例如 `android-sig gen --help`、`android-sig help veri`。

### `gen`：生成或复用，并同步

```bash
# 生成到 /root/android-signing/demo-app-signing/，默认上传 GitHub Secrets
sudo android-sig gen octocat/demo-app

# 指定本地名称：/root/android-signing/my-key-signing/
sudo android-sig gen octocat/demo-app my-key

# 只在本地生成，不要求 gh / GitHub 连接
sudo android-sig gen octocat/demo-app --local-only
```

如果目录已存在且包含合法 `metadata.json`，`gen` 会验证并复用**同一份**证书，不会更新私钥。遇到没有 metadata 的旧目录会中止，并要求先运行 `adopt`。如果目标 GitHub 仓库已经存在任何同名签名 Secret，但本地目录尚不存在，会拒绝创建新密钥，以免破坏已发布 APK 的更新连续性。仅在明确接受签名更换风险时才使用 `--replace-secrets`。

### `adopt`：迁移旧版目录（**不换签名**）

已有如下目录：

```text
/root/android-signing/demo-app-signing/
├── release.p12
└── release.p12.password.txt
```

其中 `release.p12.password.txt` 支持两种格式：

```text
passwd=<你的原有密码>
```

或者单行纯密码。`adopt` 会解析原来的私钥 Alias，验证 PKCS#12 / CSR / X.509 与有效期，然后**只新增** `metadata.json`（保存仓库名、Alias、指纹等非秘密信息），不修改 `.p12` 和密码内容：

```bash
sudo android-sig adopt octocat/demo-app

# 原来的本地目录叫 old-app-signing/，不是 demo-app-signing/
sudo android-sig adopt octocat/demo-app old-app

# 如果想迁移完成后立即上传 GitHub Secrets：
sudo android-sig adopt octocat/demo-app old-app --sync
```

如果一个 PKCS#12 中有多个私钥条目，可指定 `--alias 原别名`。对已绑定其他仓库的目录，工具会拒绝重新绑定，避免误共享签名。

**已有项目迁移顺序**：检查旧 `.p12` 和密码备份 → `adopt` → `veri` → `sync` → 从 Actions 构建 APK → `veri --apk`。不必删除或重新生成旧密钥。

### `sync`：重新上传 GitHub Secrets

```bash
sudo android-sig sync octocat/demo-app
sudo android-sig sync octocat/demo-app old-app
```

仅允许同步已经建立仓库绑定的目录。该操作会覆盖目标仓库的四个同名 Secrets；上传过程中部分成功、部分失败时，原本地签名不受影响，可重试。GitHub 不提供四个 Secret 的事务式更新。

### `veri`：证书与 APK 验证

```bash
# 本地：密码 / PrivateKeyEntry / CSR 私钥证明 / 证书公钥 / 有效期 / 指纹
sudo android-sig veri octocat/demo-app

# 同时检查 GitHub Actions 中四个 Secret 的名称是否存在
sudo android-sig veri octocat/demo-app --remote

# 独立验证 APK 的真实签名
android-sig veri --apk ./app-release.apk

# 验证 APK 的真实签名，且要求与指定本地证书的 SHA-256 一致
sudo android-sig veri octocat/demo-app --apk ./app-release.apk

# 机器可读输出
sudo android-sig veri octocat/demo-app --json
```

`--remote` 仅能检查 Secrets **是否存在**，不能读取它们的明文、比较与本地 `.p12` 的内容是否一致。APK 匹配校验由 `apksigner verify --print-certs` 实际验证签名后再比较证书 SHA-256；不是仅检查文件名或哈希。

### `list`：查看全部签名

```bash
sudo android-sig list
sudo android-sig list --verbose
sudo android-sig list --json
```

显示 `VALID` / `UNBOUND` / `INVALID`，`UNBOUND` 指旧目录尚未执行 `adopt`。

## 本地文件

```text
/root/android-signing/
├── .android-sig.lock
├── demo-app-signing/
│   ├── release.p12                  # 私钥 + X.509 证书，权限 0600
│   ├── release.p12.password.txt     # 密码，权限 0600
│   └── metadata.json                # 仓库绑定信息，权限 0600
└── another-app-signing/
    └── ...
```

目录权限为 `0700`。默认加密参数：RSA 3072、PKCS12、Alias `release`、自签证书有效期 `36500` 天、48 位随机十六进制密码（24 字节随机源）。历史签名的 Alias 不会被覆盖。

## GitHub Actions 对接

同步到目标仓库的 Actions Secrets（**不进入 git 历史**）：

| Secret 名称 | 内容 |
| --- | --- |
| `SIGNING_KEYSTORE_BASE64` | PKCS#12 文件的 Base64 内容 |
| `SIGNING_PASSWORD` | 密钥库密码 |
| `SIGNING_KEY_PASSWORD` | 私钥密码；本工具生成时与密钥库密码相同 |
| `SIGNING_KEY_ALIAS` | 实际 PrivateKeyEntry Alias |

在工作流中可以这样恢复：

```yaml
- name: Restore signing keystore
  env:
    SIGNING_KEYSTORE_BASE64: ${{ secrets.SIGNING_KEYSTORE_BASE64 }}
  run: |
    printf '%s' "$SIGNING_KEYSTORE_BASE64" | base64 --decode > release.p12

- name: Build signed APK
  env:
    SIGNING_STORE_PASSWORD: ${{ secrets.SIGNING_PASSWORD }}
    SIGNING_KEY_PASSWORD: ${{ secrets.SIGNING_KEY_PASSWORD }}
    SIGNING_KEY_ALIAS: ${{ secrets.SIGNING_KEY_ALIAS }}
  run: |
    # 让项目的 Gradle signingConfig 或 apksigner 读取这些环境变量。
    # 具体构建命令取决于 APK 项目。
    echo 'Configure the project signing step here'
```

不要将密码打印到日志、写入生成产物、传递给公开 CI 任务或使用来自不可信 fork 的代码读取 Secrets。项目 CI 需自行接入签名配置，本工具不会自动编辑目标仓库。

## 安全与限制

1. **务必备份**：`.p12` 和密码文件必须一起保留；GitHub Secrets 不可作为恢复备份。建议离线加密备份，且不把明文密码上传到云盘或 Git 仓库。
2. **不会自动轮换**：更新已发布应用的签名密钥可能导致无法覆盖安装。损坏或丢失密钥时本工具默认报错，不会擅自生成替代品。
3. **仓库绑定**：`metadata.json` 包含证书 SHA-256 和目标仓库标识；若目录已绑定到另一仓库则拒绝使用。导入历史目录须明确使用 `adopt`。
4. **验证范围**：本地证书验证不代表有公共 CA 背书；APK 是否被正确签名由 `apksigner` 判断。`--remote` 不支持对远程秘密做字节级核对。
5. **运行环境**：工具依赖 Linux 文件锁，不支持 Windows 原生运行。使用 Android SDK `apksigner` 要求 SDK Build Tools 正确安装。
6. **不共享密钥**：即使库是公开的，`/root/android-signing` 的数据仅驻留在运行工具的本地服务器，仓库内不得提交任何真实签名材料。

## 开发和测试

```bash
python3 -m unittest discover -s tests -v
```

测试只使用临时目录与示例仓库名，不访问真实 GitHub，不生成任何真实项目的签名材料。

## License

MIT；详见 [LICENSE](LICENSE)。