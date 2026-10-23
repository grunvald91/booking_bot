"""Names only: which settings the studio api container has, and how its compose files feed it. No values."""
import json, re, subprocess
c = json.loads(subprocess.check_output(["docker", "inspect", "ai-growth-os-api-1"], text=True))[0]
names = sorted(item.split("=", 1)[0] for item in c["Config"]["Env"])
print("container_env_names=" + ",".join(n for n in names if n.startswith(("SERVGO", "DISPATCH", "LLM", "ANTHROPIC", "DEEPSEEK", "OPENAI", "MODEL", "DATABASE", "STUDIO", "AGENT"))))
labels = c["Config"]["Labels"]
files = labels["com.docker.compose.project.config_files"].split(",")
print("compose_files=" + ",".join(files))
for path in files:
    try:
        text = open(path, encoding="utf-8").read()
    except OSError:
        print("unreadable " + path); continue
    print("--- " + path)
    service = None
    for line in text.splitlines():
        if re.match(r"^  [a-z0-9_-]+:\s*$", line):
            service = line.strip()
        if "env_file" in line:
            print(f"[{service}] {line.strip()}")
        m = re.match(r"^\s+- (.+)$", line)
        match = re.match(r"^\s+(env_file|\.env)", line)
        key = re.match(r"^\s{6,}([A-Z][A-Z0-9_]+):", line)
        if key and service == "api:":
            print(f"[api] env key {key.group(1)}")
print("dotenv_names=" + ",".join(sorted(l.split("=",1)[0] for l in open("/opt/ai_growth_os/.env") if "=" in l and not l.startswith("#") and l.split("=",1)[0].startswith(("SERVGO","DISPATCH","LLM","MODEL","STUDIO")))))
