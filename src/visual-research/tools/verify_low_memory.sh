#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOCK_DIR="${TMPDIR:-/tmp}/megalophobia-low-memory.lock"
VERIFY_TMP=""
RUN_GAMETEST=false
RUN_WORLDGEN_SMOKE=false

for option in "$@"; do
  case "$option" in
    --gametest)
      RUN_GAMETEST=true
      ;;
    --worldgen-smoke)
      RUN_WORLDGEN_SMOKE=true
      ;;
    --all)
      RUN_GAMETEST=true
      RUN_WORLDGEN_SMOKE=true
      ;;
    *)
      echo "Unknown option: $option" >&2
      echo "Usage: $0 [--gametest] [--worldgen-smoke] [--all]" >&2
      exit 2
      ;;
  esac
done

cleanup() {
  if [[ -n "$VERIFY_TMP" && -d "$VERIFY_TMP" ]]; then
    rm -rf "$VERIFY_TMP"
  fi
  rm -f "$LOCK_DIR/pid"
  rmdir "$LOCK_DIR" 2>/dev/null || true
}

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  LOCK_PID="$(sed -n '1p' "$LOCK_DIR/pid" 2>/dev/null || true)"
  if [[ "$LOCK_PID" =~ ^[0-9]+$ ]] && kill -0 "$LOCK_PID" 2>/dev/null; then
    echo "Refusing to start: verification process $LOCK_PID already holds $LOCK_DIR." >&2
    exit 2
  fi
  rm -f "$LOCK_DIR/pid"
  rmdir "$LOCK_DIR" 2>/dev/null || true
  if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    echo "Refusing to start: unable to acquire $LOCK_DIR." >&2
    exit 2
  fi
fi
printf '%s\n' "$$" > "$LOCK_DIR/pid"
trap cleanup EXIT INT TERM

if pgrep -f 'org.gradle.launcher.daemon.bootstrap.GradleDaemon|net.neoforged.devlaunch.Main|javac.*megalophobia' >/dev/null 2>&1; then
  echo "Refusing to start: another Gradle or Minecraft development JVM is already running." >&2
  echo "Stop that run first, then retry. This guard prevents overlapping multi-GB JVMs." >&2
  exit 2
fi

cd "$PROJECT_ROOT"

NEO_VERSION="$(sed -n 's/^neo_version=//p' gradle.properties | head -1)"
RUNTIME_LIBS="${MEGALOPHOBIA_RUNTIME_LIBS:-${HOME}/Library/Application Support/Modernity/runtimes/neoforge-${NEO_VERSION}/libraries}"
JAVAC_BIN="${MEGALOPHOBIA_JAVAC:-$(command -v javac || true)}"
JAVA_BIN="${MEGALOPHOBIA_JAVA:-$(command -v java || true)}"

if [[ ! -d "$RUNTIME_LIBS" || -z "$JAVAC_BIN" || -z "$JAVA_BIN" ]]; then
  echo "The cached NeoForge runtime or Java compiler was not found; using the bounded Gradle path." >&2
  export GRADLE_OPTS="${GRADLE_OPTS:-} -Djava.net.preferIPv4Stack=true"
  python3 tools/run_with_timeout.py 180 nice -n 10 \
    ./gradlew --offline --no-daemon --max-workers=1 lightweightCheck processResources jar
else
  VERIFY_TMP="$(mktemp -d /tmp/megalophobia-verify.XXXXXX)"

  CLASSPATH=""
  while IFS= read -r dependency; do
    CLASSPATH="${CLASSPATH:+${CLASSPATH}:}${dependency}"
  done < <(find "$RUNTIME_LIBS" -type f -name '*.jar' -print | sort)

  MAIN_SOURCES=()
  while IFS= read -r source; do
    MAIN_SOURCES+=("$source")
  done < <(find src/main/java -type f -name '*.java' -print | sort)
  TEST_SOURCES=()
  while IFS= read -r source; do
    TEST_SOURCES+=("$source")
  done < <(find src/test/java -type f -name '*.java' -print | sort)

  mkdir -p "$VERIFY_TMP/main" "$VERIFY_TMP/test"
  python3 tools/run_with_timeout.py 90 nice -n 10 \
    "$JAVAC_BIN" -J-Xms32m -J-Xmx256m -J-XX:+UseSerialGC \
    --release 25 -encoding UTF-8 -cp "$CLASSPATH" -d "$VERIFY_TMP/main" "${MAIN_SOURCES[@]}"
  python3 tools/run_with_timeout.py 90 nice -n 10 \
    "$JAVAC_BIN" -J-Xms32m -J-Xmx128m -J-XX:+UseSerialGC \
    --release 25 -encoding UTF-8 -cp "$VERIFY_TMP/main:$CLASSPATH" \
    -d "$VERIFY_TMP/test" "${TEST_SOURCES[@]}"
  python3 tools/run_with_timeout.py 60 nice -n 10 \
    "$JAVA_BIN" -Xms16m -Xmx64m -XX:+UseSerialGC \
    -cp "$VERIFY_TMP/test:$VERIFY_TMP/main:$CLASSPATH" \
    com.modernity.megalophobia.LightweightAlgorithmChecks

  # Install only the already-verified classes into Gradle's generated output.
  # The exact target is disposable build output, never source or world data.
  rm -rf "$PROJECT_ROOT/build/classes/java/main"
  mkdir -p "$PROJECT_ROOT/build/classes/java"
  cp -R "$VERIFY_TMP/main" "$PROJECT_ROOT/build/classes/java/main"

  export GRADLE_OPTS="${GRADLE_OPTS:-} -Djava.net.preferIPv4Stack=true"
  python3 tools/run_with_timeout.py 120 nice -n 10 \
    ./gradlew --offline --no-daemon --max-workers=1 \
    processResources jar -x compileJava
fi

if [[ "$RUN_GAMETEST" == true || "$RUN_WORLDGEN_SMOKE" == true ]]; then
  CACHED_LAUNCHER_URI="$(python3 tools/prepare_offline_manifest.py)"
fi

if [[ "$RUN_GAMETEST" == true ]]; then
  python3 tools/run_with_timeout.py 180 nice -n 10 \
    ./gradlew --offline --no-daemon --max-workers=1 \
    --init-script "$PROJECT_ROOT/tools/offline_launcher.init.gradle" \
    "-Dmodernity.cachedLauncherManifest=$CACHED_LAUNCHER_URI" \
    runGameTestServer -x compileJava
fi

if [[ "$RUN_WORLDGEN_SMOKE" == true ]]; then
  if [[ -z "$VERIFY_TMP" ]]; then
    VERIFY_TMP="$(mktemp -d /tmp/megalophobia-verify.XXXXXX)"
  fi
  WORLDGEN_SMOKE_DIR="$VERIFY_TMP/worldgen-smoke"
  mkdir -p "$WORLDGEN_SMOKE_DIR"
  cp tools/worldgen-smoke-server.properties "$WORLDGEN_SMOKE_DIR/server.properties"
  python3 tools/run_with_timeout.py 180 nice -n 10 \
    ./gradlew --offline --no-daemon --max-workers=1 \
    --init-script "$PROJECT_ROOT/tools/offline_launcher.init.gradle" \
    "-Dmodernity.cachedLauncherManifest=$CACHED_LAUNCHER_URI" \
    "-PmegalophobiaSmokeDir=$WORLDGEN_SMOKE_DIR" \
    runWorldgenSmoke -x compileJava
  if [[ ! -f "$WORLDGEN_SMOKE_DIR/worldgen-smoke.ok" ]]; then
    if [[ -f "$WORLDGEN_SMOKE_DIR/worldgen-smoke.fail" ]]; then
      echo "Worldgen smoke failure: $(<"$WORLDGEN_SMOKE_DIR/worldgen-smoke.fail")" >&2
    else
      echo "Worldgen smoke run exited without a result marker." >&2
    fi
    exit 1
  fi
  echo "Megalophobia worldgen smoke passed: $(<"$WORLDGEN_SMOKE_DIR/worldgen-smoke.ok")"
fi
