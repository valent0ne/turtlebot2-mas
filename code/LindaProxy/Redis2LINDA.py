
"""
Copyright 2017-2018 Agnese Salutari.
Licensed under the Apache License, Version 2.0 (the "License"); 
you may not use this file except in compliance with the License. 
You may obtain a copy of the License at

http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on 
an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. 
See the License for the specific language governing permissions and limitations under the License
"""

import lindaproxy as lp
import redis


def makeAtomic(s):
    out = s.replace('(', 'A')
    out = out.replace(')', 'B')
    out = out.replace('[', 'C')
    out = out.replace(']', 'D')
    out = out.replace('.', 'E')
    out = out.replace(',', 'F')
    out = out.replace('/', 'G')
    out = out.replace('\\', 'H')
    out = out.replace("'", 'I')
    out = out.replace(' ', 'O')
    out = out.replace(':', 'J')
    return out


# used to send message to the DALI MAS
L = lp.LindaProxy(host='127.0.0.1')
L.connect()

# prepare and forward the messages to the MAS
R = redis.Redis()
pubsub = R.pubsub()
pubsub.subscribe('LINDAchannel')
print('listening on LINDAchannel...')
for item in pubsub.listen():
    if item['type']=='message':
        msg = item['data'].decode('utf-8')
        separator = msg.index(':')
        # get addressee
        addressee = msg[:separator]
        # remove addressee from the message body
        msg = msg[separator+1:]
        atomic = makeAtomic(msg)
        print('--- redis event ---')
        print('addressee: {}'.format(addressee))
        print('message: {}'.format(msg))
        print('atomic: {}'.format(atomic))
        L.send_message(addressee, "redis(" + atomic + ")")
