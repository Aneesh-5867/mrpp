xterm -e "roscore" &
sleep 3
xterm -e "rosparam load $1" &
sleep 2
xterm -e "rosrun mrpp_sumo sumo_wrapper.py" &
sleep 3
xterm -e "rosrun mrpp_sumo 4_sim_rl_true.py" &
sleep 2
xterm -e "rosrun mrpp_sumo command_center.py"
sleep 3
killall xterm & sleep 5
