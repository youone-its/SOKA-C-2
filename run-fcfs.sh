#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
mvn -q -pl modules/cloudsim-examples -am compile -DskipTests
mvn -q -pl modules/cloudsim org.apache.maven.plugins:maven-dependency-plugin:2.8:build-classpath -Dmdep.outputFile=target/fcfs-classpath.txt
fcfs_dependencies=$(cat modules/cloudsim/target/fcfs-classpath.txt)
java -cp "modules/cloudsim-examples/target/classes:modules/cloudsim/target/classes:$fcfs_dependencies" \
  org.cloudbus.cloudsim.examples.FCFS.FCFS_Scheduler "$@"
