#!/usr/bin/env bash

set -e

if [[ "$OSTYPE" == "darwin"* ]]; then
	realpath() { [[ $1 = /* ]] && echo "$1" || echo "$PWD/${1#./}"; }
	ROOT=$(dirname "$(dirname "$(realpath "$0")")")
else
	ROOT=$(dirname "$(dirname "$(readlink -f $0)")")
	# If the script is running in Docker using the WSL2 engine, powershell.exe won't exist
	if grep -qi Microsoft /proc/version && type powershell.exe > /dev/null 2>&1; then
		IN_WSL=true
	fi
fi


function ensure_sandbox_daemon() {
	local MOD_ROOT
	MOD_ROOT="$(cd "$ROOT/../.." && pwd)"
	local WS="/tmp/modernity-workspace"
	local RT="$WS/daemon.json"
	local LOG="$WS/daemon.log"
	if [[ ! -f "$MOD_ROOT/services/sandbox/daemon.py" ]]; then
		return 0
	fi
	mkdir -p "$WS" 2>/dev/null || true
	if [[ -d "/tmp/jdks/jdk-25.0.3.jdk/Contents/Home" ]]; then
		export JAVA_HOME="/tmp/jdks/jdk-25.0.3.jdk/Contents/Home"
	elif [[ -d "$HOME/AAI/modernity/.jdks/jdk-25.0.3+9/Contents/Home" ]]; then
		export JAVA_HOME="$HOME/AAI/modernity/.jdks/jdk-25.0.3+9/Contents/Home"
	else
		JH=$(/usr/libexec/java_home -v 25 2>/dev/null || true)
		if [[ -n "$JH" ]]; then
			export JAVA_HOME="$JH"
		fi
	fi
	export GRADLE_OPTS="-Djava.net.preferIPv4Stack=true"
	export PATH="$JAVA_HOME/bin:$PATH"
	PYTHON_CANDIDATES=("/usr/bin/python3" "python3" "python")
	DAEMON_PY=""
	for PY in "${PYTHON_CANDIDATES[@]}"; do
		if (PYTHONPATH="$MOD_ROOT" "$PY" -c "import uvicorn, fastapi" 2>/dev/null); then
			DAEMON_PY="$PY"
			break
		fi
	done
	if [[ -z "$DAEMON_PY" ]]; then
		DAEMON_PY="python3"
	fi
	if [[ -f "$RT" ]]; then
		if (cd "$MOD_ROOT" && PYTHONPATH="$MOD_ROOT" "$DAEMON_PY" -c "from services.sandbox.client import SandboxDaemonClient; c=SandboxDaemonClient.from_runtime_file('$RT'); c.health()" 2>/dev/null); then
			echo "[code.sh] Sandbox daemon already running ($RT)" >&2
			return 0
		fi
		rm -f "$RT" 2>/dev/null || true
	fi
	echo "[code.sh] Starting sandbox daemon: workspace=$WS runtime=$RT log=$LOG python=$DAEMON_PY" >&2
	(cd "$MOD_ROOT" && PYTHONPATH="$MOD_ROOT" nohup "$DAEMON_PY" -m services.sandbox.daemon start --workspace-root "$WS" --runtime-file "$RT" --host 127.0.0.1 --port 0 > "$LOG" 2>&1 &)
	for i in {1..20}; do
		sleep 0.5
		if [[ -f "$RT" ]]; then
			if (cd "$MOD_ROOT" && PYTHONPATH="$MOD_ROOT" "$DAEMON_PY" -c "from services.sandbox.client import SandboxDaemonClient; c=SandboxDaemonClient.from_runtime_file('$RT'); c.health()" 2>/dev/null); then
				echo "[code.sh] Sandbox daemon started (port $(cd "$MOD_ROOT" && PYTHONPATH="$MOD_ROOT" "$DAEMON_PY" -c "import json; print(json.load(open('$RT')).get('port','?'))" 2>/dev/null))" >&2
				return 0
			fi
		fi
	done
	echo "[code.sh] Warning: sandbox daemon failed to start quickly, see $LOG" >&2
	return 0
}


function ensure_inference_gateway() {
	local MOD_ROOT
	MOD_ROOT="$(cd "$ROOT/../.." && pwd)"
	local GW_PORT=8000
	local GW_LOG="/tmp/modernity-workspace/inference.log"
	local GW_PIDFILE="/tmp/modernity-workspace/inference.pid"

	if lsof -i :${GW_PORT} -sTCP:LISTEN >/dev/null 2>&1; then
		if curl -s http://127.0.0.1:${GW_PORT}/api/inference/v1/models >/dev/null 2>&1 || curl -s http://127.0.0.1:${GW_PORT}/health >/dev/null 2>&1; then
			echo "[code.sh] Inference gateway already running on :${GW_PORT}" >&2
			return 0
		fi
	fi

	local API_KEY="${MODEL_API_KEY:-}"
	if [[ -z "$API_KEY" && -f "$MOD_ROOT/.env" ]]; then
		API_KEY=$(grep -E "^MODEL_API_KEY=" "$MOD_ROOT/.env" 2>/dev/null | cut -d= -f2- | tr -d '"'"'")
	fi
	if [[ -z "$API_KEY" ]]; then
		for SETTINGS in "$HOME/Library/Application Support/Modernity/User/settings.json" "$HOME/Library/Application Support/code-oss-dev/User/settings.json"; do
			if [[ -f "$SETTINGS" ]]; then
				API_KEY=$(python3 -c "import json,sys; p=sys.argv[1];
try:
    d=json.load(open(p))
    sec=d.get('modernity.dev',{}).get('secrets',{})
    print(sec.get('MODEL_API_KEY','') or sec.get('LLM_API_KEY','') or '')
except Exception:
    print('')" "$SETTINGS" 2>/dev/null)
				if [[ -n "$API_KEY" ]]; then
					echo "[code.sh] Found MODEL_API_KEY in $SETTINGS" >&2
					break
				fi
			fi
		done
	fi

	if [[ -z "$API_KEY" ]]; then
		API_KEY="dummy-dev-key"
		echo "[code.sh] MODEL_API_KEY not found, using dummy (mock fallback)" >&2
	fi

	local PY_CANDIDATES=("python3" "python3.12" "python3.11" "/usr/local/bin/python3.12" "/Applications/Xcode_26.2.0_17C52_fb.app/Contents/Developer/Library/Frameworks/Python3.framework/Versions/3.9/Resources/Python.app/Contents/MacOS/Python")
	local GW_PY=""
	for PY in "${PY_CANDIDATES[@]}"; do
		if [[ "$PY" == /* ]]; then [[ -x "$PY" ]] || continue; else command -v "$PY" >/dev/null 2>&1 || continue; fi
		if ! "$PY" -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" 2>/dev/null; then continue; fi
		if (PYTHONPATH="$MOD_ROOT" "$PY" -c "import fastapi, uvicorn, openai" 2>/dev/null); then GW_PY="$PY"; break; fi
	done
	if [[ -z "$GW_PY" ]]; then GW_PY="/Applications/Xcode_26.2.0_17C52_fb.app/Contents/Developer/Library/Frameworks/Python3.framework/Versions/3.9/Resources/Python.app/Contents/MacOS/Python"; fi

	mkdir -p "$(dirname "$GW_LOG")" 2>/dev/null || true

	local APP_MODULE="services.backend.api.minimal_inference_gateway:app"
	local APP_DIR="$MOD_ROOT"

	# Fallback to /tmp/minimal_inference:app if repo module missing
	if [[ ! -f "$MOD_ROOT/services/backend/api/minimal_inference_gateway.py" && -f "/tmp/minimal_inference.py" ]]; then
		APP_MODULE="minimal_inference:app"
		APP_DIR="/tmp"
	fi

	echo "[code.sh] Starting inference gateway :${GW_PORT} via $GW_PY $APP_MODULE" >&2
	(MODEL_API_KEY="$API_KEY" MODEL_BASE_URL="${MODEL_BASE_URL:-https://api.meta.ai/v1}" PYTHONPATH="$MOD_ROOT" nohup "$GW_PY" -m uvicorn "$APP_MODULE" --app-dir "$APP_DIR" --host 127.0.0.1 --port $GW_PORT --log-level info > "$GW_LOG" 2>&1 & echo $! > "$GW_PIDFILE")
	for i in {1..20}; do
		sleep 0.5
		if curl -s http://127.0.0.1:${GW_PORT}/api/inference/v1/models >/dev/null 2>&1; then
			echo "[code.sh] Inference gateway started on :${GW_PORT}" >&2
			return 0
		fi
	done
	echo "[code.sh] Warning: inference gateway failed to start, see $GW_LOG" >&2
	return 0
}


function code() {
	cd "$ROOT"

	# T280149056: auto-start sandbox daemon before Electron launch
	ensure_sandbox_daemon || true
	ensure_inference_gateway || true

	if [[ "$OSTYPE" == "darwin"* ]]; then
		NAME=`node -p "require('./product.json').nameLong"`
		EXE_NAME=`node -p "require('./product.json').nameShort"`
		CODE="./.build/electron/$NAME.app/Contents/MacOS/$EXE_NAME"
	else
		NAME=`node -p "require('./product.json').applicationName"`
		CODE=".build/electron/$NAME"
	fi

	# Get electron, compile, built-in extensions
	if [[ -z "${VSCODE_SKIP_PRELAUNCH}" ]]; then
		node build/lib/preLaunch.ts
	fi

	# Manage built-in extensions
	if [[ "$1" == "--builtin" ]]; then
		exec "$CODE" build/builtin
		return
	fi

	# Configuration
	export NODE_ENV=development
	export VSCODE_DEV=1
	export VSCODE_CLI=1
	export ELECTRON_ENABLE_STACK_DUMPING=1
	export ELECTRON_ENABLE_LOGGING=1

	DISABLE_TEST_EXTENSION="--disable-extension=vscode.vscode-api-tests"
	if [[ "$@" == *"--extensionTestsPath"* ]]; then
		DISABLE_TEST_EXTENSION=""
	fi

	# Launch Code
	exec "$CODE" . $DISABLE_TEST_EXTENSION "$@"
}

function code-wsl()
{
	HOST_IP=$(echo "" | powershell.exe -noprofile -Command "& {(Get-NetIPAddress | Where-Object {\$_.InterfaceAlias -like '*WSL*' -and \$_.AddressFamily -eq 'IPv4'}).IPAddress | Write-Host -NoNewline}")
	export DISPLAY="$HOST_IP:0"

	# in a wsl shell
	ELECTRON="$ROOT/.build/electron/Code - OSS.exe"
	if [ -f "$ELECTRON"  ]; then
		local CWD=$(pwd)
		cd $ROOT
		export WSLENV=ELECTRON_RUN_AS_NODE/w:VSCODE_DEV/w:$WSLENV
		local WSL_EXT_ID="ms-vscode-remote.remote-wsl"
		local WSL_EXT_WLOC=$(echo "" | VSCODE_DEV=1 ELECTRON_RUN_AS_NODE=1 "$ROOT/.build/electron/Code - OSS.exe" "out/cli.js" --locate-extension $WSL_EXT_ID)
		cd $CWD
		if [ -n "$WSL_EXT_WLOC" ]; then
			# replace \r\n with \n in WSL_EXT_WLOC
			local WSL_CODE=$(wslpath -u "${WSL_EXT_WLOC%%[[:cntrl:]]}")/scripts/wslCode-dev.sh
			$WSL_CODE "$ROOT" "$@"
			exit $?
		else
			echo "Remote WSL not installed, trying to run VSCode in WSL."
		fi
	fi
}

if [ "$IN_WSL" == "true" ] && [ -z "$DISPLAY" ]; then
	code-wsl "$@"
elif [ -f /mnt/wslg/versions.txt ]; then
	code --disable-gpu "$@"
elif [ -f /.dockerenv ]; then
	# Workaround for https://bugs.chromium.org/p/chromium/issues/detail?id=1263267
	# Chromium does not release shared memory when streaming scripts
	# which might exhaust the available resources in the container environment
	# leading to failed script loading.
	code --disable-dev-shm-usage "$@"
else
	code "$@"
fi

exit $?
