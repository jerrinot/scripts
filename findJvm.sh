#!/bin/bash

if [ -z "$1" ]
  then
    echo "No argument supplied. Usage: findJvm.sh <name>"
    exit 1
fi
name=$1

line=$(jps|grep $name)
#echo $line

lineCount=$(echo "$line" | wc -l)
#echo $lineCount

if [ "$lineCount" -eq "0" ]; then
   echo "No JVM with name $name found";
   exit 2;
fi

if [ "$lineCount" -gt "1" ]; then
   echo "Multiple JVMs with name $name found";
   exit 3;
fi

pid=$(echo "$line"|awk '{print $1}')
echo $pid
