#!/usr/bin/env python3


'''
Observation model based approach
AN_MRPP
epsilon-greedy
Simple Exponential Smoothing (SES)


ROS Params
'''
import rospy
import rospkg
import numpy as np
import networkx as nx
from mrpp_sumo.srv import NextTaskBot, NextTaskBotResponse, AlgoReady, AlgoReadyResponse
from mrpp_sumo.msg import AtNode
import random as rn
import csv
import math

class AN_MRPP:

    def __init__(self, graph, num_bots):
        self.ready = False
        self.graph = graph
        self.stamp = 0.
        self.num_bots = num_bots
        self.vel = 10.                                #MAX VELOCITY SET FOR SIMULATIONS
        self.nodes = list(self.graph.nodes())

        self.current_node = {}
        self.old_node = {}

        self.idle_expect = {}                         #expected idlness: depends on bot,prev node, current node
        self.idle_true = {}                           #true idlness :    depends only on current node
        self.value_func = {}                          #value function :  equal to expected total reward for an agent starting from state s
                                                      #                 and taking action a(current node is our state s, action a is the next node we move to)

        self.value_exp = {}                           #fraction of (exponential of the value_func [selecting this current node])
                                                      #            (sum of exponential of all value func [other nodes it couldve went to from the old node])


        self.store = {}                               #this is a nested dictionary storing the true idleness values when a bot visits a node.
                                                      # It will be used to compute the expected idlness by taking the average of
                                                      #   true idleness the bot has observed on its previous visits to the current from a particular old node
                                                      # (hence it depends on which edge has been taken to reach this current node)

        for i in range(self.num_bots):
            self.idle_expect['bot_{}'.format(i)] = {}
            self.value_func['bot_{}'.format(i)] = {}
            self.value_exp['bot_{}'.format(i)] = {}
            self.store['bot_{}'.format(i)] = {}
            self.current_node['bot_{}'.format(i)] = None
            self.old_node['bot_{}'.format(i)] = None

            for n in self.nodes:
                self.idle_expect['bot_{}'.format(i)][n] = {}
                self.value_func['bot_{}'.format(i)][n] = {}
                self.value_exp['bot_{}'.format(i)][n] = {}
                self.store['bot_{}'.format(i)][n] = {}

                for m in self.graph.successors(n):
                    self.idle_expect['bot_{}'.format(i)][n][m] = self.graph[n][m]['length']/self.vel
                    self.value_func['bot_{}'.format(i)][n][m] = 0
                    self.value_exp['bot_{}'.format(i)][n][m] = 1./(len(list(self.graph.successors(n))))
                    self.store['bot_{}'.format(i)][n][m] = []

        for n in self.nodes:
            self.idle_true[n] = 0.

        self.ready = True

    def callback_idle(self, data):
        if self.stamp < data.stamp:
            dev = data.stamp - self.stamp
            self.stamp = data.stamp

            #update current node
            for i,n in enumerate(data.robot_id):
                self.current_node[n] = data.node_id[i]

            #update true idleness
            for n in self.nodes:
                self.idle_true[n] += dev

            #The very first case, old node is None, the following wont be executed
            for i,n in enumerate(data.robot_id):
                if self.old_node[n] is not None :
                    #add the true idleness to the storage data structure
                    if len(self.store[n][self.old_node[n]][self.current_node[n]]) < 5:
                        self.store[n][self.old_node[n]][self.current_node[n]].append(self.idle_true[data.node_id[i]])

                    #taking only 5 past values to predict the true idleness
                    if len(self.store[n][self.old_node[n]][self.current_node[n]]) == 5:
                        self.store[n][self.old_node[n]][self.current_node[n]].pop(0)
                        self.store[n][self.old_node[n]][self.current_node[n]].append(self.idle_true[data.node_id[i]])

            #estimating the expected idleness by simple exponential smoothing technique using the true idleness data in self.store
            for i in self.store.keys():
                for j in self.store[i].keys():
                    for m in self.store[i][j].keys():
                        sum = 0
                        leng = len(self.store[i][j][m])
                        alpha = 0.4

                        #if we have atleast 5 past values apply SES
                        if leng > 4:
                            for k in range(leng):
                                #simple exponential smoothing
                                sum += ((1-alpha)**k)*self.store[i][j][m][-k-1]
                                self.idle_expect[i][j][m] = alpha*sum

                        #if we have less than 5, just predict the last observed true idleness as expected idleness
                        if leng < 5 and leng > 1 :
                            self.idle_expect[i][j][m] = self.store[i][j][m][-2]
                        if leng == 1:
                            self.idle_expect[i][j][m] = self.stamp

            for i, n in enumerate(data.robot_id):
                with open('{}.csv'.format(n), 'a+', newline='') as file:
                    writer = csv.writer(file)
                    if self.old_node[n] is not None :

                        expect = self.idle_expect[n][self.old_node[n]][self.current_node[n]]
                        true = self.idle_true[self.current_node[n]]
                        t = self.stamp

                        #learning rate and gamma in Q learning
                        lr = 0.1
                        gamma = 0.95

                        #calculating(updating) the value function for the action from old node to current node
                        if expect > true:
                            reward = -(math.log(expect -true))
                            self.value_func[n][self.old_node[n]][self.current_node[n]] += lr*(reward + gamma*max(self.value_func[n][self.current_node[n]].values())- self.value_func[n][self.old_node[n]][self.current_node[n]])
                        elif true > expect:
                            reward = (math.log(true - expect))
                            self.value_func[n][self.old_node[n]][self.current_node[n]] += lr*(reward + gamma*max(self.value_func[n][self.current_node[n]].values())- self.value_func[n][self.old_node[n]][self.current_node[n]])
                        else:
                            reward = 0
                            self.value_func[n][self.old_node[n]][self.current_node[n]] += lr*(reward + gamma*max(self.value_func[n][self.current_node[n]].values())- self.value_func[n][self.old_node[n]][self.current_node[n]])

                        #calculating the exponential of value function and summing the all possibilties to 1
                        summ = 0
                        for m in self.graph.successors(self.old_node[n]):
                            summ += math.exp(self.value_func[n][self.old_node[n]][m] * self.idle_expect[n][self.old_node[n]][self.current_node[n]] )                          #also adding the contribution of the expected idleness

                        for m in self.graph.successors(self.old_node[n]):
                            self.value_exp[n][self.old_node[n]][m] = (math.exp(self.value_func[n][self.old_node[n]][m] * self.idle_expect[n][self.old_node[n]][self.current_node[n]]))/summ

                        #wrting the data into a csv file
                        writer.writerow([t,self.graph[self.old_node[n]][self.current_node[n]]['name'],self.old_node[n],self.current_node[n],self.value_exp[n][self.old_node[n]][self.current_node[n]],self.value_func[n][self.old_node[n]][self.current_node[n]],self.idle_expect[n][self.old_node[n]][self.current_node[n]],self.idle_true[self.current_node[n]],self.idle_expect[n][self.old_node[n]][self.current_node[n]]-self.idle_true[self.current_node[n]],len(list(self.graph.successors(self.old_node[n])))])

            #set current node as old node
            for i,n in enumerate(data.robot_id):
                self.old_node[n] = data.node_id[i]

            #set true idleness to zero as we have just visited the node
            for i in enumerate(data.node_id):
                self.idle_true[i] = 0.

    def callback_next_task(self, req):
        node = req.node_done
        t = req.stamp
        bot = req.name

        #set true idleness to zero as we are just about to leave this node
        self.idle_true[node] = 0.

        neigh = list(self.graph.successors(node))
        rand = rn.random()
        epsilon = 0.15

        #epsilon greedy
        if rand > epsilon:
            idles = []
            for n in neigh:
                idles.append(self.value_exp[bot][node][n])

            max_id = 0
            if len(neigh) > 1:
                max_ids = list(np.where(idles == np.amax(idles))[0])
                max_id = rn.sample(max_ids, 1)[0]
            #exploitation
            next_walk = [node, neigh[max_id]]
            next_departs = [t]
            return NextTaskBotResponse(next_departs, next_walk)

        else :
            #exploration
            next_node = rn.sample(neigh, 1)[0]
            next_walk = [node, next_node]
            next_departs = [t]
            return NextTaskBotResponse(next_departs, next_walk)

    def callback_ready(self, req):
        algo_name = req.algo
        if algo_name == 'ses' and self.ready:
            return AlgoReadyResponse(True)
        else:
            return AlgoReadyResponse(False)

if __name__ == '__main__':
    rospy.init_node('AN_MRPP', anonymous = True)
    dirname = rospkg.RosPack().get_path('mrpp_sumo')
    done = False
    graph_name = rospy.get_param('/graph')
    num_bots = rospy.get_param ('/init_bots')
    g = nx.read_graphml(dirname + '/graph_ml/' + graph_name + '.graphml')

    s = AN_MRPP(g, num_bots)

    rospy.Subscriber('at_node', AtNode, s.callback_idle)
    rospy.Service('bot_next_task', NextTaskBot, s.callback_next_task)
    rospy.Service('algo_ready', AlgoReady, s.callback_ready)
    while not done:
        done = rospy.get_param('/done')
