#!/usr/bin/env bash
set -euo pipefail

echo "[code-intel] installing optional code intelligence toolchain"

INSTALL_BIN_DIR="${INSTALL_BIN_DIR:-/usr/local/bin}"
TOOL_CACHE_ROOT="${TOOL_CACHE_ROOT:-/opt/octryx}"
mkdir -p "${INSTALL_BIN_DIR}" "${TOOL_CACHE_ROOT}"

if command -v go >/dev/null 2>&1; then
  go_cache_dir="$(mktemp -d)"
  go_mod_dir="$(mktemp -d)"
  export GOCACHE="${go_cache_dir}"
  export GOMODCACHE="${go_mod_dir}"
  zoekt_version="${ZOEKT_VERSION:-latest}"
  GOBIN="${INSTALL_BIN_DIR}" go install "github.com/sourcegraph/zoekt/cmd/zoekt-index@${zoekt_version}"
  GOBIN="${INSTALL_BIN_DIR}" go install "github.com/sourcegraph/zoekt/cmd/zoekt-git-index@${zoekt_version}"
  GOBIN="${INSTALL_BIN_DIR}" go install "github.com/sourcegraph/zoekt/cmd/zoekt@${zoekt_version}"
  GOBIN="${INSTALL_BIN_DIR}" go install "github.com/sourcegraph/zoekt/cmd/zoekt-webserver@${zoekt_version}"
  GOBIN="${INSTALL_BIN_DIR}" go install github.com/sourcegraph/scip/cmd/scip@latest || true
  GOBIN="${INSTALL_BIN_DIR}" go install github.com/scip-code/scip-go/cmd/scip-go@latest || true
  rm -rf "${go_cache_dir}" "${go_mod_dir}"
else
  echo "[code-intel] go is required to install Zoekt binaries" >&2
  exit 1
fi

for binary in zoekt-index zoekt-git-index zoekt zoekt-webserver; do
  if ! command -v "${binary}" >/dev/null 2>&1; then
    echo "[code-intel] required Zoekt binary missing after install: ${binary}" >&2
    exit 1
  fi
done

if command -v npm >/dev/null 2>&1; then
  npm_cache_dir="$(mktemp -d)"
  npm install -g --cache "${npm_cache_dir}" tree-sitter-cli @sourcegraph/scip-typescript @sourcegraph/scip-python || true
  rm -rf "${npm_cache_dir}"
fi

if command -v java >/dev/null 2>&1 && command -v mvn >/dev/null 2>&1; then
  if ! command -v scip-java >/dev/null 2>&1; then
    tmp_dir="$(mktemp -d)"
    version="${SCIP_JAVA_VERSION:-0.10.4}"
    scip_java_home="${SCIP_JAVA_HOME:-${TOOL_CACHE_ROOT}/scip-java/${version}}"
    lib_dir="${scip_java_home}/lib"
    mkdir -p "${lib_dir}"
    cat > "${tmp_dir}/pom.xml" <<EOF
<project xmlns="http://maven.apache.org/POM/4.0.0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 https://maven.apache.org/xsd/maven-4.0.0.xsd">
  <modelVersion>4.0.0</modelVersion>
  <groupId>local.scip</groupId>
  <artifactId>scip-java-bootstrap</artifactId>
  <version>1.0.0</version>
  <dependencies>
    <dependency>
      <groupId>com.sourcegraph</groupId>
      <artifactId>scip-java_2.13</artifactId>
      <version>${version}</version>
    </dependency>
  </dependencies>
</project>
EOF
    maven_repo_dir="$(mktemp -d)"
    mvn -q -Dmaven.repo.local="${maven_repo_dir}" -f "${tmp_dir}/pom.xml" dependency:copy-dependencies -DincludeScope=runtime -DoutputDirectory="${lib_dir}" || true
    rm -rf "${maven_repo_dir}"
    if [ -d "${lib_dir}" ] && [ -n "$(find "${lib_dir}" -maxdepth 1 -name '*.jar' -print -quit)" ]; then
      cat > "${tmp_dir}/scip-java" <<EOF
#!/usr/bin/env bash
exec java -cp "${lib_dir}/*" com.sourcegraph.scip_java.ScipJava "\$@"
EOF
      chmod +x "${tmp_dir}/scip-java"
      mv "${tmp_dir}/scip-java" "${INSTALL_BIN_DIR}/scip-java"
    fi
    rm -rf "${tmp_dir}"
  fi
fi

echo "[code-intel] installation complete"
