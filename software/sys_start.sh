#!/bin/sh

while true; do
	cmd_gpio set_func pc11 output0
	sleep 1
	cmd_gpio set_func pc11 output1
	sleep 1
done
