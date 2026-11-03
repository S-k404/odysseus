#!/bin/bash
# update-all.sh — fast, parallel updater for ALL of Shamit's Docker stacks and images.
#
# What it does, in order:
#   1. Preflight   : Verifies Docker daemon is running; ensures high-speed download
#                   concurrency settings (max-concurrent-downloads) in ~/.docker/daemon.json.
#   2. Odysseus git: Runs `git pull --autostash --ff-only` in Odysseus repo so compose
#                   files and configurations are fresh before image pulling.
#   3. Discovery   : Discovers ALL compose projects across ~/Documents/Docker/
#                   (running and stopped, including nested stacks like Obsidian/livesync
#                   and custom compose files like llm-proxy).
#                   Also discovers MCP tool images (MCP Search Server) and any other
#                   standalone Docker images present on the host.
#                   NO projects are skipped by default (Kavita, OpenFOAM, etc. are included).
#   4. Fast Pulls  : Pulls ALL images in PARALLEL across concurrent worker slots
#                   (default: 4 parallel jobs, configurable via -j / --jobs).
#                   Dramatically cuts total download time compared to sequential pulls.
#                   Skips buildable services and local-only images without spurious errors.
#   5. Recreate    : Recreates RUNNING stacks with their new images:
#                   - Odysseus: `docker compose up -d --build`
#                   - Immich: checks major-version safety (blocks v2 -> v3 unless --allow-major),
#                     backs up PostgreSQL database via pg_dumpall, then `up -d`.
#                   - All other running stacks: `docker compose up -d`.
#                   - Stopped stacks STAY stopped (images are fresh and ready for next start).
#   6. Standalone  : Updates running non-compose containers (docker run / minecraft-* etc.)
#                   via a one-shot Watchtower run: pulls the image and recreates each
#                   changed container with its original options. Ephemeral --rm
#                   containers are left alone (they use the new image on next launch).
#   7. Pruning     : Removes dangling images if --prune is passed.
#
# Usage: update-all.sh [OPTIONS]
#   --dry-run       show what would run, change nothing
#   --prune         remove dangling images afterwards
#   --allow-major   permit Immich major-version upgrades (read release notes first!)
#   -j, --jobs N    number of parallel pull downloads (default: 4)
#   --skip PROJ     space- or comma-separated project/container names to skip
#   --no-standalone skip updating non-compose (docker run) containers
#   -h, --help      show this help message

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
DOCKER_ROOT="$HOME/Documents/Docker"
ODYSSEUS_DIR="$DOCKER_ROOT/Odysseus"
MCP_SCRIPT_DIR="$DOCKER_ROOT/MCP Search Server"
BACKUP_DIR="$DOCKER_ROOT/backups/immich"
KEEP_BACKUPS=5
LOG_FILE="$HOME/Library/Logs/docker-update-all.log"

DRY_RUN=0; PRUNE=0; ALLOW_MAJOR=0; NO_STANDALONE=0; PARALLEL_JOBS=4
SKIP_PROJECTS="${SKIP_PROJECTS:-}"

# ------------------------------------------------------------- argument parsing
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run)     DRY_RUN=1 ;;
    --prune)       PRUNE=1 ;;
    --allow-major) ALLOW_MAJOR=1 ;;
    --no-standalone) NO_STANDALONE=1 ;;
    -j|--jobs|--parallel)
      shift
      if [ $# -eq 0 ] || ! [[ "$1" =~ ^[0-9]+$ ]] || [ "$1" -lt 1 ]; then
        echo "error: -j/--jobs requires a positive integer" >&2
        exit 1
      fi
      PARALLEL_JOBS="$1"
      ;;
    --skip)
      shift
      if [ $# -eq 0 ]; then
        echo "error: --skip requires a project name" >&2
        exit 1
      fi
      SKIP_PROJECTS="$SKIP_PROJECTS $1"
      ;;
    -h|--help)
      awk 'NR>1 { if (/^#/) print; else exit }' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "unknown flag: $1 (see --help)"
      exit 1
      ;;
  esac
  shift
done

mkdir -p "$(dirname "$LOG_FILE")"
exec > >(tee -a "$LOG_FILE") 2>&1

FAILURES=""
say()  { printf '\n\033[1;36m== %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m!! %s\033[0m\n' "$*"; }
fail() { printf '\033[1;31mXX %s\033[0m\n' "$*"; FAILURES="$FAILURES\n  - $*"; }
info() { printf '   %s\n' "$*"; }
run()  {
  echo "+ $*"
  [ "$DRY_RUN" -eq 1 ] && return 0
  "$@"
}

is_skipped() {
  local needle
  needle=$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')
  local n
  for n in $SKIP_PROJECTS; do
    local clean_n
    clean_n=$(printf '%s' "$n" | tr -d ',' | tr '[:upper:]' '[:lower:]')
    [ -n "$clean_n" ] && [ "$needle" = "$clean_n" ] && return 0
  done
  return 1
}

START_TIME=$(date +%s)
echo ""
echo "=================================================================="
echo " docker update-all — $(date '+%Y-%m-%d %H:%M:%S')"
echo " Mode: $( [ "$DRY_RUN" -eq 1 ] && echo "DRY-RUN (no changes)" || echo "LIVE" ) | Concurrency: ${PARALLEL_JOBS} parallel downloads"
echo "=================================================================="

# ----------------------------------------------------------------- 1. Preflight
docker info >/dev/null 2>&1 || { fail "Docker isn't running — start Docker Desktop first."; exit 1; }

# Fast downloads: check if Docker daemon concurrency is tuned
DAEMON_JSON="$HOME/.docker/daemon.json"
if [ -f "$DAEMON_JSON" ] && command -v jq >/dev/null 2>&1; then
  cur_conc=$(jq -r '."max-concurrent-downloads" // empty' "$DAEMON_JSON" 2>/dev/null)
  if [ -z "$cur_conc" ] || [ "$cur_conc" -lt 8 ]; then
    if jq '. + {"max-concurrent-downloads": 10, "max-concurrent-uploads": 10}' "$DAEMON_JSON" > "$DAEMON_JSON.tmp" 2>/dev/null; then
      mv "$DAEMON_JSON.tmp" "$DAEMON_JSON"
      info "Optimized $DAEMON_JSON with max-concurrent-downloads: 10"
    fi
  fi
fi

# Ensure required external volume for Speaches / Odysseus exists
if ! docker volume inspect speaches_speaches_cache >/dev/null 2>&1; then
  run docker volume create speaches_speaches_cache >/dev/null 2>&1 || true
fi

# -------------------------------------------------- 2. Odysseus git pre-update
if [ -d "$ODYSSEUS_DIR/.git" ]; then
  say "Odysseus: checking git repository"
  if ! is_skipped "odysseus"; then
    (
      cd "$ODYSSEUS_DIR" || exit 1
      run git pull --autostash --ff-only
    ) || warn "Odysseus: git pull failed (conflict or diverged branch) — skipping git update"
  else
    warn "Odysseus: in SKIP_PROJECTS — skipping git pull"
  fi
fi

# ---------------------------------------------- 3. Discover all compose stacks
# Format in project list:
#   PROJ_NAME | DIR | CONFIG_FILES_COMMA_SEPARATED | IS_RUNNING (1 or 0)
say "Discovering Docker stacks and images"

# Discovered compose projects map
DISCOVERED_PROJECTS=""
seen_dirs_lower=" "

# A. From active / existing containers (exact compose working dir & config files)
while IFS='|' read -r c_proj c_dir c_files; do
  [ -z "$c_proj" ] || [ -z "$c_dir" ] && continue
  [ ! -d "$c_dir" ] && continue

  dir_lc=$(printf '%s' "$c_dir" | tr '[:upper:]' '[:lower:]')
  case "$seen_dirs_lower" in
    *" $dir_lc "*) continue ;;
  esac
  seen_dirs_lower="${seen_dirs_lower}${dir_lc} "

  if is_skipped "$c_proj" || is_skipped "$(basename "$c_dir")"; then
    warn "$c_proj: in SKIP_PROJECTS — skipped"
    continue
  fi

  is_running=0
  if [ -n "$(docker ps --filter "label=com.docker.compose.project=$c_proj" -q 2>/dev/null)" ]; then
    is_running=1
  fi

  DISCOVERED_PROJECTS="${DISCOVERED_PROJECTS}${c_proj}|${c_dir}|${c_files}|${is_running}
"
done < <(docker ps -a --format '{{.Label "com.docker.compose.project"}}|{{.Label "com.docker.compose.project.working_dir"}}|{{.Label "com.docker.compose.project.config_files"}}' 2>/dev/null | sort -u)

# B. From filesystem: scan for any compose files up to depth 4
while IFS= read -r -d '' compose_file; do
  dir=$(dirname "$compose_file")
  dir_lc=$(printf '%s' "$dir" | tr '[:upper:]' '[:lower:]')

  case "$seen_dirs_lower" in
    *" $dir_lc "*) continue ;;
  esac
  seen_dirs_lower="${seen_dirs_lower}${dir_lc} "

  # Skip specialized VPS configurations or backup dirs
  case "$dir" in
    *"/headscale/server"*) continue ;;
    *"$BACKUP_DIR"*) continue ;;
    *"$MCP_SCRIPT_DIR"*) continue ;;
  esac

  pname=$(basename "$dir")
  if is_skipped "$pname"; then
    warn "$pname: in SKIP_PROJECTS — skipped"
    continue
  fi

  DISCOVERED_PROJECTS="${DISCOVERED_PROJECTS}${pname}|${dir}|${compose_file}|0
"
done < <(find "$DOCKER_ROOT" -mindepth 2 -maxdepth 4 \
          \( -name "*compose*.yml" -o -name "*compose*.yaml" \) \
          ! -path "*/.*/*" ! -path "*/backups/*" ! -path "*/cases/*" \
          ! -path "*/data/*" ! -path "*/tests/*" ! -path "*/node_modules/*" \
          ! -path "*/.venv/*" -print0 2>/dev/null)

DISCOVERED_PROJECTS=$(printf '%s\n' "$DISCOVERED_PROJECTS" | sed '/^$/d' | sort -t'|' -k1,1 -u)

# C. Discover MCP Search Server images
MCP_IMAGES=""
if [ -d "$MCP_SCRIPT_DIR" ]; then
  MCP_IMAGES=$(grep -h "docker run" "$MCP_SCRIPT_DIR"/run-*.sh 2>/dev/null \
               | tr ' ' '\n' \
               | grep -E '^[a-zA-Z0-9][a-zA-Z0-9./_:-]*/[a-zA-Z0-9._:-]+$' \
               | grep -v ':/' | grep -v '^/' | sort -u)
fi

# Print discovery inventory
running_count=0
stopped_count=0
while IFS='|' read -r p_name p_dir p_files p_run; do
  [ -z "$p_name" ] && continue
  if [ "$p_run" -eq 1 ]; then
    info "Stack (running): $p_name  -->  $p_dir"
    running_count=$((running_count + 1))
  else
    info "Stack (stopped): $p_name  -->  $p_dir"
    stopped_count=$((stopped_count + 1))
  fi
done < <(printf '%s\n' "$DISCOVERED_PROJECTS")

mcp_count=0
if [ -n "$MCP_IMAGES" ]; then
  for m_img in $MCP_IMAGES; do
    info "MCP Image: $m_img"
    mcp_count=$((mcp_count + 1))
  done
fi

info "Discovered $running_count running stacks, $stopped_count stopped stacks, $mcp_count MCP tool images."

# ------------------------------------------- 4. Build parallel pull task list
TMP_DIR=$(mktemp -d /tmp/docker-update-all.XXXXXX)
trap 'rm -rf "$TMP_DIR"' EXIT

task_count=0
declare -a TASK_TYPES
declare -a TASK_LABELS
declare -a TASK_DIRS
declare -a TASK_CMDS

add_compose_task() {
  local name="$1"
  local dir="$2"
  local files="$3"

  local -a f_args
  f_args=()
  IFS=',' read -r -a f_list <<< "$files"
  for f in "${f_list[@]}"; do
    [ -n "$f" ] && f_args+=("-f" "$f")
  done

  TASK_TYPES[$task_count]="compose"
  TASK_LABELS[$task_count]="Stack: $name"
  TASK_DIRS[$task_count]="$dir"
  local cmd="docker compose"
  for f in "${f_list[@]}"; do
    [ -n "$f" ] && cmd="$cmd -f '$f'"
  done
  cmd="$cmd pull --ignore-buildable"
  TASK_CMDS[$task_count]="$cmd"
  task_count=$((task_count + 1))
}

add_image_task() {
  local label="$1"
  local img="$2"

  TASK_TYPES[$task_count]="image"
  TASK_LABELS[$task_count]="$label: $img"
  TASK_DIRS[$task_count]="$DOCKER_ROOT"
  TASK_CMDS[$task_count]="docker pull '$img'"
  task_count=$((task_count + 1))
}

# 1. Add all compose projects to pull queue
while IFS='|' read -r p_name p_dir p_files p_run; do
  [ -z "$p_name" ] && continue
  add_compose_task "$p_name" "$p_dir" "$p_files"
done < <(printf '%s\n' "$DISCOVERED_PROJECTS")

# 2. Add MCP images
if [ -n "$MCP_IMAGES" ]; then
  for m_img in $MCP_IMAGES; do
    add_image_task "MCP" "$m_img"
  done
fi

# 3. Add any standalone Docker images present locally
all_local_images=$(docker images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null | grep -v '<none>' | sort -u)
for loc_img in $all_local_images; do
  repo="${loc_img%:*}"
  tag="${loc_img##*:}"
  
  [ "$tag" = "local" ] && continue
  
  already_queued=0
  for m_img in $MCP_IMAGES; do
    if [ "$m_img" = "$loc_img" ] || [ "$m_img" = "$repo" ]; then
      already_queued=1; break
    fi
  done
  [ "$already_queued" -eq 1 ] && continue

  if [[ "$repo" =~ [/] ]]; then
    is_in_queue=0
    for ((k=0; k<task_count; k++)); do
      if [ "${TASK_TYPES[$k]}" = "image" ] && [[ "${TASK_CMDS[$k]}" == *"$loc_img"* ]]; then
        is_in_queue=1; break
      fi
    done
    if [ "$is_in_queue" -eq 0 ]; then
      case "$loc_img" in
        odysseus-*|better-vertsh-*|ascii-dino*|obsidian-couchdb*|*test*) ;;
        *) add_image_task "Image" "$loc_img" ;;
      esac
    fi
  fi
done

# ------------------------------------------- 5. Execute parallel downloads
say "Pulling updates in parallel ($task_count download targets, concurrency: $PARALLEL_JOBS)"

run_pull_worker() {
  local job_id="$1"
  local job_dir="$2"
  local job_cmd="$3"
  local log_out="$TMP_DIR/job_${job_id}.log"
  local exit_out="$TMP_DIR/job_${job_id}.exit"

  if [ "$DRY_RUN" -eq 1 ]; then
    echo "DRY RUN: (cd '$job_dir' && $job_cmd)" > "$log_out"
    echo 0 > "$exit_out"
    return 0
  fi

  (
    cd "$job_dir" 2>/dev/null && eval "$job_cmd"
  ) > "$log_out" 2>&1
  echo $? > "$exit_out"
}

launched=0
completed=0

report_job() {
  local idx="$1"
  local lbl="${TASK_LABELS[$idx]}"
  local ec_file="$TMP_DIR/job_${idx}.exit"
  local log_file="$TMP_DIR/job_${idx}.log"

  local ec
  ec=$(cat "$ec_file" 2>/dev/null || echo 1)

  if [ "$ec" -eq 0 ]; then
    if grep -qE "(Downloaded newer image|Pulled)" "$log_file" 2>/dev/null; then
      printf ' \033[1;32m✔\033[0m [%d/%d] %s: \033[1;32mUPDATED (newer layers downloaded)\033[0m\n' "$completed" "$task_count" "$lbl"
    else
      printf ' \033[1;32m✔\033[0m [%d/%d] %s: up to date\n' "$completed" "$task_count" "$lbl"
    fi
  else
    if grep -qiE "(not found|access denied|repository does not exist|no image to be pulled|missing a value)" "$log_file" 2>/dev/null; then
      printf ' \033[1;34mℹ\033[0m [%d/%d] %s: local / build-only service (skipped remote pull)\n' "$completed" "$task_count" "$lbl"
    else
      printf ' \033[1;31m✘\033[0m [%d/%d] %s: pull failed\n' "$completed" "$task_count" "$lbl"
      local err_snippet
      err_snippet=$(tail -n 2 "$log_file" | tr '\n' ' ')
      warn "  Error details: $err_snippet"
      fail "$lbl: pull failed"
    fi
  fi
}

check_all_completed() {
  for ((i=0; i<launched; i++)); do
    if [ ! -f "$TMP_DIR/reported_$i" ] && [ -f "$TMP_DIR/job_${i}.exit" ]; then
      touch "$TMP_DIR/reported_$i"
      completed=$((completed + 1))
      report_job "$i"
    fi
  done
}

for ((i=0; i<task_count; i++)); do
  while [ $(jobs -rp | wc -l) -ge "$PARALLEL_JOBS" ]; do
    check_all_completed
    sleep 0.05
  done
  check_all_completed

  run_pull_worker "$i" "${TASK_DIRS[$i]}" "${TASK_CMDS[$i]}" &
  launched=$((launched + 1))
done

while [ "$completed" -lt "$task_count" ]; do
  check_all_completed
  sleep 0.05
done
wait
check_all_completed

say "All image downloads completed"

# -------------------------------------- 6. Recreate / restart running stacks
say "Applying updates to running containers"

# 1. Odysseus
if [ -d "$ODYSSEUS_DIR" ] && ! is_skipped "odysseus"; then
  if [ -n "$(docker ps --filter "label=com.docker.compose.project=odysseus" -q 2>/dev/null)" ]; then
    say "Odysseus: rebuilding and restarting running stack"
    (
      cd "$ODYSSEUS_DIR" || exit 1
      run docker compose up -d --build
    ) || fail "Odysseus: compose up --build failed"
  else
    info "Odysseus: not currently running (images fresh, left stopped)"
  fi
fi

# 2. Immich
immich_line=$(printf '%s\n' "$DISCOVERED_PROJECTS" | grep -E '^immich\|')
if [ -n "$immich_line" ]; then
  IFS='|' read -r im_name im_dir im_files im_run <<< "$immich_line"

  if [ "$im_run" -eq 1 ] && docker ps --filter "label=com.docker.compose.project=immich" --format '{{.Names}}' | grep -qx 'immich_postgres'; then
    say "Immich: database backup and container update"

    cur_major=$(curl -fsS --max-time 5 http://localhost:2283/api/server/version 2>/dev/null \
                | sed -n 's/.*"major" *: *\([0-9]*\).*/\1/p')
    new_major=$(curl -fsS --max-time 10 https://api.github.com/repos/immich-app/immich/releases/latest 2>/dev/null \
                | sed -n 's/.*"tag_name" *: *"v\([0-9]*\).*/\1/p')
    if [ -n "$cur_major" ] && [ -n "$new_major" ] && [ "$cur_major" != "$new_major" ] && [ "$ALLOW_MAJOR" -eq 0 ]; then
      warn "Immich v$cur_major -> v$new_major is a MAJOR upgrade. Skipping container recreation."
      warn "Read https://github.com/immich-app/immich/releases then rerun with --allow-major."
    else
      db_user="postgres"
      [ -f "$im_dir/.env" ] && db_user=$(sed -n 's/^DB_USERNAME=//p' "$im_dir/.env" | tail -1)
      db_user="${db_user:-postgres}"
      mkdir -p "$BACKUP_DIR"
      backup="$BACKUP_DIR/immich_db_$(date +%Y%m%d_%H%M%S).sql.gz"
      echo "+ pg_dumpall (user: $db_user) -> $backup"
      if [ "$DRY_RUN" -eq 1 ] || docker exec -t immich_postgres pg_dumpall --clean --if-exists --username="$db_user" | gzip > "$backup"; then
        if [ "$DRY_RUN" -eq 1 ] || [ -s "$backup" ]; then
          ls -t "$BACKUP_DIR"/immich_db_*.sql.gz 2>/dev/null | tail -n +"$((KEEP_BACKUPS + 1))" | xargs rm -f 2>/dev/null
          
          local_cmd="docker compose"
          IFS=',' read -r -a im_flist <<< "$im_files"
          for f in "${im_flist[@]}"; do
            [ -n "$f" ] && local_cmd="$local_cmd -f '$f'"
          done
          local_cmd="$local_cmd up -d"
          echo "+ $local_cmd"
          if [ "$DRY_RUN" -eq 0 ]; then
            ( cd "$im_dir" && eval "$local_cmd" ) || fail "Immich: update failed"
          fi
        else
          rm -f "$backup"; fail "Immich: backup file was empty — update aborted"
        fi
      else
        rm -f "$backup"; fail "Immich: DB backup failed — update aborted"
      fi
    fi
  else
    info "Immich: not running — images pulled, DB left untouched"
  fi
fi

# 3. All other compose projects
while IFS='|' read -r p_name p_dir p_files p_run; do
  [ -z "$p_name" ] && continue
  [ "$p_name" = "odysseus" ] && continue
  [ "$p_name" = "immich" ] && continue

  if [ "$p_run" -eq 1 ]; then
    say "Recreating running stack: $p_name ($p_dir)"
    local_cmd="docker compose"
    IFS=',' read -r -a p_flist <<< "$p_files"
    for f in "${p_flist[@]}"; do
      [ -n "$f" ] && local_cmd="$local_cmd -f '$f'"
    done
    local_cmd="$local_cmd up -d"
    echo "+ $local_cmd"
    if [ "$DRY_RUN" -eq 0 ]; then
      ( cd "$p_dir" && eval "$local_cmd" ) || fail "$p_name: restart failed"
    fi
  else
    info "Stack '$p_name' is stopped — images updated, left stopped"
  fi
done < <(printf '%s\n' "$DISCOVERED_PROJECTS")

# ------------------------------------------- 7. Update standalone containers
# Containers started by hand (docker run ...) have no compose file to re-up, so
# they're handed to a one-shot Watchtower, which pulls the image and recreates
# each changed container with its original options (ports, mounts, env, network).
# nickfedor/watchtower is the maintained fork; containrrr/watchtower is archived.
say "Updating standalone containers"
if [ "$NO_STANDALONE" -eq 1 ]; then
  info "Skipped (--no-standalone)"
else
  WATCHTOWER_IMAGE="${WATCHTOWER_IMAGE:-nickfedor/watchtower:latest}"
  standalone=()
  ids=$(docker ps -q 2>/dev/null)
  if [ -n "$ids" ]; then
    while IFS='|' read -r s_name s_proj s_rm; do
      s_name="${s_name#/}"
      [ -z "$s_name" ] && continue
      [ -n "$s_proj" ] && continue                      # compose-managed: handled above
      case "$s_name" in *watchtower*) continue ;; esac  # never recreate a Watchtower itself
      if [ "$s_rm" = "true" ]; then
        info "$s_name: ephemeral (--rm) — picks up the freshly pulled image on next launch"
        continue
      fi
      if is_skipped "$s_name"; then
        warn "$s_name: in SKIP_PROJECTS — skipped"
        continue
      fi
      standalone+=("$s_name")
    done < <(docker inspect --format '{{.Name}}|{{index .Config.Labels "com.docker.compose.project"}}|{{.HostConfig.AutoRemove}}' $ids 2>/dev/null)
  fi

  if [ "${#standalone[@]}" -eq 0 ]; then
    info "No standalone containers to update."
  else
    info "Standalone containers: ${standalone[*]}"
    wt_args=(--run-once)
    [ "$PRUNE" -eq 1 ] && wt_args+=(--cleanup)
    run docker run --pull always --rm \
      -v /var/run/docker.sock:/var/run/docker.sock \
      "$WATCHTOWER_IMAGE" "${wt_args[@]}" "${standalone[@]}" \
      || fail "Standalone containers: Watchtower run failed"
  fi
fi

# ------------------------------------------------------------------ 8. Prune
if [ "$PRUNE" -eq 1 ]; then
  say "Pruning dangling images"
  run docker image prune -f
fi

# ----------------------------------------------------------------- Summary
END_TIME=$(date +%s)
ELAPSED=$((END_TIME - START_TIME))

echo ""
echo "=================================================================="
if [ -n "$FAILURES" ]; then
  printf ' Finished in %ds WITH ERRORS:%b\n' "$ELAPSED" "$FAILURES"
  exit 1
else
  printf ' All done in %ds! Log saved to: %s\n' "$ELAPSED" "$LOG_FILE"
fi
echo "=================================================================="
