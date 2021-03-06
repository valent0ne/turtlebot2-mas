import math
import struct
import time
import numpy as np
import redis

try:
    import vrep

except ImportError as e:
    print('--------------------------------------------------------------')
    print('"vrep.py" could not be imported. This means very probably that')
    print('either "vrep.py" or the remoteApi library could not be found.')
    print('Make sure both are in the same folder as this file,')
    print('or appropriately adjust the file "vrep.py"')
    print('--------------------------------------------------------------')
    print(e)


class World(object):
    """
    Robot simulator class to communicate with the simulation environment.
    """

    def __init__(self, sensors, wheels, signals, plate, host='127.0.0.1', port=19999, terminal=None):
        """
        initialize the connection to vrep and retrieves the handler
        :param sensors: list of the names of the sensor devices
        :param wheels: list of the names of the wheel parts
        :param signals: list of the names of the signals
        :param plate: handle of the top plate
        :param host: ip of the vrep simulator
        :param port: port of the vrep simulator
        :param terminal: terminal object that will be used for logging
        """
        # turtning speed
        self._turning_speed = 1.5
        self._host = host
        self._port = port
        self._term = terminal
        # starting load condition
        self._load = "EMPTY"
        # handle of the carried cube object
        self._cube_handle = None

        # just in case, close all opened connections
        vrep.simxFinish(-1)
        # enstablish the connection
        self._clientID = vrep.simxStart(self._host, self._port, True, True, 5000, 5)
        # connection error
        if self._clientID == -1:
            terminal.write('Connection to the server was not possible')
            exit(1)
        # default operation mode
        self._operation_mode = vrep.simx_opmode_blocking

        self.wheels_handles = {}
        self.sensors_handles = {}
        self.signals = signals

        # fetch wheel handles
        self._term.write('Fetching wheels handles...')
        for w in wheels:
            res, handle = vrep.simxGetObjectHandle(self._clientID, wheels[w], self._operation_mode)
            if res == vrep.simx_return_ok:
                self.wheels_handles[w] = handle
            else:
                self._term.write('Wheels handle error: {}'.format(res))
                exit(1)

        # fetch sensors handles
        self._term.write('Fetching sensors handles...')
        for s in sensors:  # initialize the robot.
            res, handle = vrep.simxGetObjectHandle(self._clientID, sensors[s], self._operation_mode)
            if res == vrep.simx_return_ok:
                self.sensors_handles[s] = handle
            else:
                self._term.write('Sensors handle error: {}'.format(res))
                exit(1)

        # fetch plate handle
        res, handle = vrep.simxGetObjectHandle(self._clientID, plate, self._operation_mode)
        if res == vrep.simx_return_ok:
            self.plate_handle = handle
        else:
            self._term.write('Plate handle error: {}'.format(res))
            exit(1)

        self._term.write("successfully fetched all handles")

    def sense(self):
        """
        Sense the world and return data
        :return: constructed dictionary of the form {DEPTH, {BLOB_COLOR, BLOB_POSITION}, BLOB_SIZE}
        """

        out = {}

        # retrieve depth data
        result, resolution, data = vrep.simxGetVisionSensorDepthBuffer(self._clientID,
                                                                       self.sensors_handles['kinect_depth'],
                                                                       self._operation_mode)
        if result != vrep.simx_return_ok:  # checking the reading result.
            exit(result)

        # get clean depth data
        out['depth'] = self.get_depth(data)  # appending the distance depth.

        # retrieve vision sensor image
        result_vision, resolution, image = vrep.simxGetVisionSensorImage(self._clientID,
                                                                         self.sensors_handles['kinect_rgb'],
                                                                         0,
                                                                         vrep.simx_opmode_blocking)
        # retrieve vision sensor filtered image (blob)
        result_blob, t0, t1 = vrep.simxReadVisionSensor(self._clientID,
                                                        self.sensors_handles['kinect_rgb'],
                                                        vrep.simx_opmode_blocking)

        # extract blob data
        out['vision'] = self.get_vision(resolution, image, t1)

        # get load status
        out['load'] = self._load

        self._term.write("sensed: {}".format(out))

        return out

    @staticmethod
    def get_depth(matrix):
        """
        extract the depth value from the depth buffer
        :param matrix: image depth buffer
        :return: depth value rounded up to the 5th digit
        """
        # 640*480 resolution
        depth = 100
        # look only at the central vertical slice
        for i in range(210, 430):
            for j in range(480):
                if matrix[i*220+j] < depth:
                    depth = matrix[i*220+j]  # update matrix.
        return round(depth, 5)

    def get_vision(self, resolution, image, blob_data):
        """
        extract blob data from vision sensor image buffer


        blob_data[0]=blob count
        blob_data[1]=n=value count per blob
        blob_data[2]=blob 1 size
        blob_data[3]=blob 1 orientation
        blob_data[4]=blob 1 position x
        blob_data[5]=blob 1 position y
        blob_data[6]=blob 1 width
        blob_data[7]=blob 1 height
        ...
        :return: {COLOR, POSITION}, SIZE
        """
        color = "NONE"
        position = "NONE"

        blob_data = blob_data[1]

        if blob_data[0] == 0:
            return color, position

        blob_size = blob_data[2]

        # get color
        color = self.get_blob_color(resolution, image)
        if color == "NONE":
            return color, position, round(blob_size, 5)

        if blob_size >= 0.65:
            return color, "NEAR", round(blob_size, 5)

        if 0.35 < blob_data[4] < 0.65:
            return color, "CENTER", round(blob_size, 5)

        if 0.0 < blob_data[4] < 0.35:
            return color, "LEFT", round(blob_size, 5)

        if 0.65 < blob_data[4] < 1:
            return color, "RIGHT", round(blob_size, 5)

        return color, position, round(blob_size, 5)

    @staticmethod
    def get_blob_color(resolution, image):
        """
        extract the blob color from an imagebuffer
        :param resolution: resolution of the image
        :param image: image buffer
        :return: blob color
        """

        image = np.array(image, dtype=np.uint8)
        detected_color = "NONE"
        colors = 3
        # the len of the image is 921600 = 640x480x3 => this means that each 3 values is a pixel
        # red = 200,41,41
        # green = 72,233,72

        for x in range(resolution[0]-3):
            y = int(resolution[1]/2)  # I only look at the line of pixels in the middle
            r = image[colors * (y * resolution[0] + x)]
            g = image[colors * (y * resolution[0] + x) + 1]
            b = image[colors * (y * resolution[0] + x) + 2]
            if r == 0 or g == 0 or b == 0:  # if black
                continue

            if g > 190:  # we detect green.
                detected_color = "GREEN"

            elif r > 190:  # we detect red.
                detected_color = "RED"

        return detected_color

    def stop(self):
        """
        Stops the unit and re-centers the carried cube, if any
        """
        self._term.write('stopped')
        # the second parameter is the velocity.
        vrep.simxSetJointTargetVelocity(self._clientID, self.wheels_handles["wheel_right"], 0, self._operation_mode)
        vrep.simxSetJointTargetVelocity(self._clientID, self.wheels_handles["wheel_left"], 0, self._operation_mode)
        # move back the package to the center of the platform
        if self._cube_handle is not None:

            return_code, plate_position = vrep.simxGetObjectPosition(self._clientID, self.plate_handle, -1,
                                                                     self._operation_mode)

            final_position = plate_position
            final_position[2] += 0.05

            vrep.simxSetObjectPosition(self._clientID, self._cube_handle, -1, final_position, self._operation_mode)
            time.sleep(0.1)

    def turn(self, speedr, speedl, angle):
        """
        turns the unit: giving speed to the left wheel makes the robot to turn right and vice-versa
        :param speedr: speed of the right wheel.
        :param speedl: speed of the left wheel.
        :param angle: turning angle.
        """
        self._term.write('turning, angle = {}'.format(angle))
        # will contain cumulative turtning angle
        z = 0
        while z < angle:
            time.sleep(1)
            # the second parameter is the velocity
            # set speed
            vrep.simxSetJointTargetVelocity(self._clientID, self.wheels_handles["wheel_right"], speedr,
                                            self._operation_mode)
            vrep.simxSetJointTargetVelocity(self._clientID, self.wheels_handles["wheel_left"], speedl,
                                            self._operation_mode)
            # get gyroscope data
            gyro_data = vrep.simxGetStringSignal(self._clientID, self.signals['gyro_signal'], self._operation_mode)
            # gyro_data_unpacked_x = (struct.unpack("f", bytearray(gyro_data[1][:4]))[0] * 180) / math.pi
            # gyro_data_unpacked_y = (struct.unpack("f", bytearray(gyro_data[1][4:8]))[0] * 180) / math.pi
            # extract degrees per second
            gyro_data_unpacked_z = (struct.unpack("f", bytearray(gyro_data[1][8:12]))[0] * 180) / math.pi
            # self._term.write('-------------------------------------------------------\n'
            #      '{} : X-Gyro = {} dps\n        Y-Gyro = {} dps\n        Z-Gyro = {} dps'
            #      .format(self._port, round(gyro_data_unpacked_x, 2), round(gyro_data_unpacked_y, 2),
            #              round(gyro_data_unpacked_z, 2)))

            # add up
            z += abs(gyro_data_unpacked_z)
            # self._term.write('cumulative angle = {}'.format(z))
        self._term.write('turn completed')

    def go(self, speed):
        """
        makes the unit go forward
        :param speed: velocity of both wheels
        """
        self._term.write('going, speed = {}'.format(speed))
        vrep.simxSetJointTargetVelocity(self._clientID, self.wheels_handles["wheel_right"], speed,
                                        self._operation_mode)
        vrep.simxSetJointTargetVelocity(self._clientID, self.wheels_handles["wheel_left"], speed,
                                        self._operation_mode)

    def loadup(self):
        """
        spawns a cube and moves it on top of the unit
        (simulating the loadup operation)
        """
        self.stop()
        self._term.write("loading up...")
        # invoke the spawnCube function defined in the vrep scene
        return_code, out_int, out_float, out_string, out_buffer = \
            vrep.simxCallScriptFunction(self._clientID,
                                        "",
                                        vrep.sim_scripttype_mainscript,
                                        "spawnCube",
                                        [],
                                        [],
                                        [],
                                        bytearray(),
                                        self._operation_mode)
        # retrieve the spawned cube handle
        self._cube_handle = out_int[0]

        # retrieve the plate position
        return_code, plate_position = vrep.simxGetObjectPosition(self._clientID,
                                                                 self.plate_handle,
                                                                 -1,
                                                                 self._operation_mode)
        # put the cube a little bit higher than the plate
        final_position = plate_position
        final_position[2] += 0.05

        # mov the cube on top of the plate
        vrep.simxSetObjectPosition(self._clientID,
                                   self._cube_handle,
                                   -1,
                                   final_position,
                                   self._operation_mode)

        # change state
        self._load = "FULL"
        self._term.write("load up completed.")
        return

    def unload(self):
        """
        abstracts the unload operation: makes the package (cube) disappear
        """
        self.stop()
        self._term.write("unloading...")

        # remove the cube
        vrep.simxRemoveObject(self._clientID, self._cube_handle, self._operation_mode)
        self._cube_handle = None

        self._term.write("unload completed.")
        self._load = "EMPTY"
        return

    # noinspection PyBroadException
    def act(self, action):
        """
        translates abstracted actions to elementary actions
        :param action: string resembling the action to perform
        :return:
        """
        separator = None
        try:
            # if we have a simple action (without other parameters)
            separator = action.index(':')
        except Exception:
            if action == 'stop':
                self.stop()
                return
            if action == 'unload':
                self.unload()
                return
            if action == 'loadup':
                self.loadup()
                return

        # if we have a complex action: extract 'action' and 'value'
        # (in this case the action is in this form: 'go:2')
        value = int(action[separator+1:])
        action = action[:separator]

        if action == 'go':
            self.go(value)
            return
        
        if action == 'right':
            self.turn(0, self._turning_speed, value)
            return
        
        if action == 'left':
            self.turn(self._turning_speed, 0, value)
            return


class Brain(object):
    """
    describes the reasoning capabilities of the unit
    """

    def __init__(self, world, port, terminal):
        """
        initialize the think module, instantiate the connection to LindaProxy
        and listen for actions coming from DALI
        :param world: world object
        :param port: port in which the agent operates in the vrep simulation (used as an identifier)
        :param terminal: terminal object used to log actions
        """
        # depth threshold that is used to detect obstacles (empirically determined)
        self._depth_treshold = 0.17
        self._world = world
        self._state = None
        # last depth value for which DALI has been called
        self._dali_depth = ""
        # number of timesin which an 'impulsive' action has been made
        # (actions that have been performed without consulting DALI)
        self._no_dali_count = 0

        self._port = port

        # build agent name
        self._agent_name = "turtlebot_{}".format(self._port)  # name of the agent.
        # topic in which DALI publishes the actions
        self._topic = "fromMAS"  # communication topic (from DALI to me).
        self._term = terminal

        # build redis clients (from DALI and to LindaProxy)
        self._to_linda = redis.Redis()
        self._from_dali = redis.Redis(host='127.0.0.1', port=6379)
        self._sub = self._from_dali.pubsub()
        self._sub.subscribe(self._topic)
        # previous performed action
        self._previous_action = None

        self._term.write("subbed to topic: {}".format(self._topic))

    def think(self, sensor_reading):
        """
        thinks and decides what to do
        :param sensor_reading: result of the sense (description of the environment)
        :return: an action
        """
        self._state, changed = self.perception(sensor_reading)
        # the world is changed of if the unit is facing the wrong direction -> call DALI.
        if changed or self._no_dali_count > 5:
            # stop the unit while DALi is computing
            self._world.act('stop')
            self._no_dali_count = 0
            action = self.decision()
            self._previous_action = action
        else:  # the world did not change
            action = self.ground_decision()
            self._no_dali_count += 1
        return action

    def perception(self, sensor_reading):
        """
        reads the sensor readings and builds a world representation
        :param sensor_reading: result of the sense
        :return: new state and a boolean that indicates if the state is changed from before
        """
        new_state = {'color': sensor_reading['vision'][0].lower(),
                     'position': sensor_reading['vision'][1].lower(),
                     'depth': sensor_reading['depth'],
                     'load': sensor_reading['load'].lower()}  # we build the new_state.

        # this is the first iteration, init the state
        if self._state is None:
            self._state = new_state.copy()
            self._dali_depth = self._state['depth']
            # to trigger the first DALI reasoning
            changed = True
        else:
            # check if the current state is different enough from the previous one
            changed = self.compare_states(self._state, new_state)
        # return new state and a boolean that indicates if the state is changed from before
        return new_state, changed

    def decision(self):
        """
        invoke the DALI agent to get an action
        :return: a decision from DALI
        """

        # update the depth that DALI knoes
        self._dali_depth = self._state['depth']

        # update the depth if for some chance it has been wrongly recorded
        if self._state['depth'] <= self._depth_treshold or self._state['position'] == 'near':
            depth = "near"
        else:
            depth = "far"

        # build the message that will be sent to the DALI agent
        vision = "vision({},{}).".format(self._state['color'], self._state['position'])
        depth = "depth({}).".format(depth)
        load = "load({}).".format(self._state['load'])
        name = "agentname('{}:').".format(str(self._port))

        # meta instructions
        meta = ":- dynamic vision/2. :- dynamic depth/1. :- dynamic load/1. :- dynamic agentname/1."

        # final message
        message = "{} {} {} {} {}".format(meta, vision, depth, load, name)

        # publish the message to the proxy
        self._to_linda.publish("LINDAchannel", self._agent_name + ':' + message)

        # wait for an answer
        self._term.write('listening for decision from MAS...')
        for item in self._sub.listen():
            if item['type'] == 'message':
                msg = item['data'].decode('utf-8')
                separator = msg.index(':')
                name = int(msg[:separator])
                # if the action is not meant for me
                if name != self._port:
                    continue
                # otherwise extract the action
                action = msg[separator+1:]
                self._term.write('received action: {}'.format(action))
                return action

    def ground_decision(self):
        """
        ground decision performed without invoking DALI
        :return: an action
        """
        if self._state['depth'] <= self._depth_treshold:
            # the unit is near something, call DALI
            return self.decision()
        # if the state is not changed and I'm not colliding then repeat the previous action
        return self._previous_action

    def compare_states(self, old_state, new_state):
        """
        compares two states and determines if they are different enough
        :param old_state: old state
        :param new_state: new state
        :return: true if the states are different, false otherwise
        """
        return old_state['color'] != new_state['color'] or \
               old_state['position'] != new_state['position'] or \
               old_state['load'] != new_state['load'] or \
               (abs(new_state['depth'] - self._dali_depth) >= 0.02)
