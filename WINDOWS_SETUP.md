# AutoGrader on Windows (WSL + Docker + Ollama)

How to start AutoGrader on a Windows laptop, and how to set it up again from scratch.
The project only runs on Linux or macOS, so on Windows it runs inside **WSL (Ubuntu)**.

Every command below goes in the **WSL (Ubuntu) terminal** unless it says **PowerShell**.
Copy and paste commands (right-click or `Ctrl+Shift+V` in the terminal) instead of typing
them: a missing space or letter breaks them.

---

## 1. Start it (every time, after a restart)

Everything is already installed, so this is all you need.

**1.1 Open the WSL terminal.** Start menu, then **Ubuntu** (or type `wsl` in PowerShell).

**1.2 Start the web interface:**

```bash
cd ~/AutoGrader
```

```bash
.venv/bin/python main.py serve
```

Expected output:

```text
AutoGrader is running at http://127.0.0.1:8000
Press Ctrl+C to stop.
```

Keep this window open. The interface only works while it runs.

**1.3 Open the page** in your Windows browser:

```text
http://127.0.0.1:8000
```

Choose a rule set, pick a sample or upload a `.c` file, tick **Add local LLM remarks** if you
want them, and press **Grade submission**.

**1.4 Stop it** by pressing `Ctrl+C` in the WSL window.

Docker and Ollama start by themselves when Ubuntu starts. You never need to run a container,
open Docker Desktop, or start Ollama by hand.

### Optional: check that everything is ready

```bash
cd ~/AutoGrader
```

```bash
.venv/bin/python main.py check-tools
```

| Line | Must show |
|------|-----------|
| `gcc` | `/usr/bin/gcc` |
| `cppcheck` | `/usr/bin/cppcheck` |
| `lizard` | `version 1.24.3` |
| `backend:docker` | available (not "unavailable") |
| `backend:seatbelt` | unavailable: macOS only. This is normal |

```bash
curl http://127.0.0.1:11434
```

Must print `Ollama is running`.

---

## 2. Grade from the command line (no browser)

One submission, with the full report printed:

```bash
cd ~/AutoGrader
```

```bash
.venv/bin/python main.py grade --source submissions/examples/add_student.c --config config/rules.json --output reports/ --print-report
```

This writes `reports/add_student.json` and `reports/add_student.txt`. The report should show
`Sandbox:  docker` and `Compiled:  yes`.

| Option | Meaning |
|--------|---------|
| `--source FILE.c` | The submission to grade |
| `--config config/rules.json` | Rules for the "add two integers" problem |
| `--config config/rules_sort.json` | Rules for the sort problem (use with `sort_*.c`) |
| `--output reports/` | Where the two reports are written |
| `--print-report` | Also print the text report in the terminal |
| `--no-llm` | Skip the LLM remarks (faster) |

A sort submission:

```bash
.venv/bin/python main.py grade --source submissions/examples/sort_bubble.c --config config/rules_sort.json --output reports/ --print-report
```

Other useful commands:

```bash
.venv/bin/python main.py validate-config --config config/rules.json
```

```bash
.venv/bin/python main.py verify-repro --source submissions/examples/add_student.c --config config/rules.json --runs 3
```

```bash
.venv/bin/python -m pytest -q
```

To open the reports folder in Windows Explorer:

```bash
explorer.exe reports
```

---

## 3. Full setup from scratch

Only needed on a new laptop, or after reinstalling Ubuntu.

### 3.1 WSL and Ubuntu (PowerShell, as administrator)

```powershell
wsl --list --verbose
```

If Ubuntu is not listed, install it and restart Windows when asked:

```powershell
wsl --install -d Ubuntu
```

Then update WSL:

```powershell
wsl --update
```

### 3.2 System packages (WSL)

```bash
sudo apt update
```

```bash
sudo apt install -y python3-venv python3-pip build-essential unzip cppcheck curl zstd
```

Check:

```bash
gcc --version && cppcheck --version && python3 --version
```

### 3.3 Copy the project into Ubuntu (WSL)

Find the ZIP in your Windows Downloads or Desktop:

```bash
ls -1 /mnt/c/Users/*/Downloads/*AutoGrader*.zip /mnt/c/Users/*/Desktop/*AutoGrader*.zip 2>/dev/null
```

Copy it, using the exact path printed above (this example is from the HP laptop):

```bash
cp "/mnt/c/Users/HP/Downloads/AutoGrader.zip" ~/
```

```bash
cd ~ && unzip -q AutoGrader.zip && cd ~/AutoGrader && ls
```

Extract inside Ubuntu, not with Windows Explorer. Explorer drops the executable flag on the
scripts, and working under `/mnt/c` is much slower.

### 3.4 Python environment (WSL)

```bash
cd ~/AutoGrader
```

```bash
python3 -m venv .venv
```

```bash
.venv/bin/python -m pip install -r requirements.txt
```

Ubuntu has no `python` command. Always use `.venv/bin/python` inside the project.

### 3.5 Fix the Docker backend (WSL, once per copy of the project)

The shipped code runs the container as user `65534`, which cannot read the grader's private
work folder, so every compile fails with `Permission denied`. This makes the container run as
your own user instead (still not root, no network, no capabilities, read-only root):

```bash
sed -i 's/"--user", "65534:65534",/"--user", f"{os.getuid()}:{os.getgid()}",/' execution/sandbox.py
```

Check:

```bash
grep -n '"--user"' execution/sandbox.py
```

It must show `f"{os.getuid()}:{os.getgid()}"`. After this change, the test in
`tests/test_sandbox.py` (line 172) that expects `65534:65534` fails until it is updated.

### 3.6 Docker inside Ubuntu (WSL)

Use Ubuntu's own Docker package. Do **not** use the snap version (`/snap/bin/docker`): it
cannot see `/tmp`, where the grader puts submissions. Quit Docker Desktop first (right-click
the whale icon, then **Quit**) so the two do not clash.

If a snap Docker is installed, remove it:

```bash
snap list 2>/dev/null | grep -i docker
```

```bash
sudo snap remove docker
```

Install Docker and give your user access:

```bash
sudo apt install -y docker.io
```

```bash
sudo usermod -aG docker $USER
```

```bash
sudo systemctl enable --now docker
```

Restart WSL so the group change takes effect. Close all WSL windows, then in **PowerShell**:

```powershell
wsl --shutdown
```

Open a new WSL terminal and check. None of these may use `sudo`:

```bash
groups
```

The output must include `docker`.

```bash
which docker
```

This must show `/usr/bin/docker`.

```bash
docker run --rm hello-world
```

### 3.7 Build the sandbox image (WSL, no `sudo`)

```bash
cd ~/AutoGrader
```

```bash
docker build -t autograder-sandbox:latest docker/
```

The "legacy builder is deprecated" warning is harmless.

```bash
.venv/bin/python main.py check-tools
```

`backend:docker` must now be available.

### 3.8 Ollama and the model (WSL, optional)

Check memory:

```bash
free -h
```

Install Ollama:

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

```bash
curl http://127.0.0.1:11434
```

If the `Mem:` total from `free -h` is 7 GB or more:

```bash
ollama pull llama3.1
```

```bash
ollama run llama3.1 "Reply with just: ok"
```

If it is less than 7 GB, use the smaller model and point the rules at it:

```bash
ollama pull llama3.2:3b
```

```bash
sed -i 's/"model": "llama3.1"/"model": "llama3.2:3b"/' config/rules.json
```

Give the model more time than the 60-second default (only needed once):

```bash
grep -q llm_timeout_s config/rules.json || sed -i 's/"temperature": 0, "seed": 42/"llm_timeout_s": 180, "temperature": 0, "seed": 42/' config/rules.json
```

The `grep -q ... ||` part skips the change if it is already there, so running it twice is safe.

```bash
.venv/bin/python main.py validate-config --config config/rules.json
```

LLM remarks are advisory: they never change the grade. Only `config/rules.json` turns them
on; `rules_sort.json` does not.

### 3.9 First run

Continue with section 1.

---

## 4. Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| Page says no sandbox available | Docker not reachable by your user, or image missing | `docker images` must list `autograder-sandbox` without `sudo`. If not, see 3.6 and 3.7. Then restart the server and press **Ctrl+F5** |
| `permission denied ... docker.sock` | Your user is not in the `docker` group yet | `groups` must show `docker`. Run `sudo usermod -aG docker $USER`, then `wsl --shutdown` in PowerShell |
| `group 'docker' does not exist` | Docker came from snap or Docker Desktop | Follow 3.6 (install `docker.io`) |
| `/snap/bin/docker: No such file or directory` | Bash remembers the removed snap path | Close the terminal and open a new one, or run `hash -r` |
| `Compiled: no` with `submission.c: Permission denied` | Docker fix not applied | Section 3.5, then grade again |
| `Cannot connect to the Docker daemon` | Docker service stopped | `sudo systemctl start docker` |
| `docker build` says it requires 1 argument | A space slipped into `docker/` | Paste exactly: `docker build -t autograder-sandbox:latest docker/` |
| `python: command not found` | Ubuntu only has `python3` | Use `.venv/bin/python` |
| `./venv/bin/python: No such file` | Typo; the folder is `.venv` | `.venv/bin/python` (dot, then `venv`) |
| `unrecognized arguments` | A space is missing, for example `--config/rules.json` | `--config config/rules.json` |
| LLM box greyed out on the page | Ollama not running | `curl http://127.0.0.1:11434`; if it fails, `sudo systemctl start ollama` |
| LLM remarks say timed out | The model is slow on CPU | Raise `llm_timeout_s` in `config/rules.json` (3.8) |
| `Address already in use` | The server is already running in another window | Close that one, or `.venv/bin/python main.py serve --port 8001` |
| Browser cannot open the page | Server not running | Start it (section 1) and keep the window open |

---

## 5. Notes for the team

- On Linux, a program that exceeds the memory limit is usually reported as `exited` (the
  allocation fails) rather than `memory_limit`, so `test_memory_limit_stops_a_large_allocation`
  fails on Linux. This needs a fix in `execution/process_runner.py`.
- Grades on Linux can differ slightly from the macOS sample reports in `reports/samples/`,
  because the compiler is different. Both are reproducible on their own toolchain.
- `--allow-unsafe` runs submissions with no isolation. Use it only for your own trusted
  samples, never for real student code.
