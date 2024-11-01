#!/usr/bin/python3
import sys
import struct
import wrapper
import threading
import time
from wrapper import recv_from_any_link, send_to_link, get_switch_mac, get_interface_name

def parse_ethernet_header(data):
    # Unpack the header fields from the byte array
    #dest_mac, src_mac, ethertype = struct.unpack('!6s6sH', data[:14])
    dest_mac = data[0:6]
    src_mac = data[6:12]
    
    # Extract ethertype. Under 802.1Q, this may be the bytes from the VLAN TAG
    ether_type = (data[12] << 8) + data[13]

    vlan_id = -1
    # Check for VLAN tag (0x8100 in network byte order is b'\x81\x00')
    if ether_type == 0x8200:
        vlan_tci = int.from_bytes(data[14:16], byteorder='big')
        vlan_id = vlan_tci & 0x0FFF  # extract the 12-bit VLAN ID
        ether_type = (data[16] << 8) + data[17]

    return dest_mac, src_mac, ether_type, vlan_id

def create_vlan_tag(vlan_id):
    # 0x8100 for the Ethertype for 802.1Q
    # vlan_id & 0x0FFF ensures that only the last 12 bits are used
    return struct.pack('!H', 0x8200) + struct.pack('!H', vlan_id & 0x0FFF)

def create_bpdu_package(root_bridge_id, sender_bridge_id, sender_path_cost):
    # '6s' for the 6-byte MAC, 'I' for each integer field (assuming they fit in 4 bytes)
    dest_mac = b"\x01\x80\xC2\x00\x00\x00"
    packet = struct.pack('6sIII', dest_mac, root_bridge_id, sender_bridge_id, sender_path_cost)
    return packet

def parse_bpdu_packet(packet):
    # Define the format string to match the packet structure
    # '6s' for 6-byte MAC address, 'I' for each 4-byte integer field
    format_string = '6sIII'
    
    # Unpack the packet based on the format string
    dest_mac, root_bridge_ID, sender_bridge_ID, sender_path_cost = struct.unpack(format_string, packet)
    
    return dest_mac, root_bridge_ID, sender_bridge_ID, sender_path_cost
    

def send_bdpu_every_sec(interfaces, switch_config, switch_id):

# Send BPDU on all trunk ports with:
#     mac_address (6 bytes)
#     root_bridge_ID = own_bridge_ID (4 bytes)
#     sender_bridge_ID = own_bridge_ID (4 bytes)
#     sender_path_cost = 0  (4 bytes)
    global own_bridge_id
    global root_bridge_id
    global root_path_cost
    global root_port
    global is_root_bridge
    global switch_port

    while True:
        if is_root_bridge:
            # # TODO Send BDPU every second if necessary
            data = create_bpdu_package(root_bridge_id, own_bridge_id, root_path_cost)
            for i in interfaces:
                if switch_config[switch_id][i] == 'T':
                    send_to_link(i, len(data), data)
        time.sleep(1)

def identify_vlan_id(switch_id, interface):
    file_name = f'configs/switch{switch_id}.cfg'

    port = get_interface_name(interface)

    with open(file_name, 'r') as file:
        for line in file:
            if line.startswith(port):
                value = line.split()[1]
                return value  # Make sure to return immediately after finding the value

    return None  # In case the port is not found

def forward_package(vlan_id, switch_id, interface_to_send, interface_received, length, data, switch_config, switch_port):
#     #1. if i want to send on the trunk i have should have the header
#     #   a. if was received from the trunk i send as i received
#     #   b. if was received from an acces port i have to include the header
#     #2. if i want to send on an acces port i should send without the header
#     #   a. if was received from the trunk i have to delete the header
#     #   b. if was received from the acces port i send as i received
    
    # first case is if i want to send to trunk and the interface trunk should be on listening
    if switch_config[switch_id][interface_to_send] == 'T' and switch_port[interface_to_send] == 1:
        if switch_config[switch_id][interface_received] == 'T': # this means is received from trunk
            send_to_link(interface_to_send, length, data)
        elif switch_config[switch_id][interface_received] != 'T': # this means is received from acces port so i have to add the header
            if vlan_id == -1:
                vlan_id = switch_config[switch_id][interface_received] # i have to update the vlan id
            tagged_frame = data[0:12] + create_vlan_tag(int(vlan_id)) + data[12:]
            tagged_length = length + 4
            send_to_link(interface_to_send, tagged_length, tagged_frame)
    if switch_config[switch_id][interface_to_send] != 'T': # this means i have to send to an acces port without the header
        if switch_config[switch_id][interface_received] == 'T' and vlan_id == int(switch_config[switch_id][interface_to_send]):  # this means is received from trunk so i have to remove the header
            without_tagged_frame = data[0:12] + data[16:]
            without_tagged_length = length - 4
            send_to_link(interface_to_send, without_tagged_length, without_tagged_frame)
        elif switch_config[switch_id][interface_received] != 'T' and switch_config[switch_id][interface_to_send] == switch_config[switch_id][interface_received]:
            send_to_link(interface_to_send, length, data)
    

def forward_vlan_broadcast(vlan_id, interfaces, interface, switch_id, length, data, switch_config, switch_port):
        for i in interfaces:
            if i != interface:
                forward_package(vlan_id, switch_id, i, interface, length, data, switch_config, switch_port)


def priority_switch(switch_id):
    file_name = f'configs/switch{switch_id}.cfg'
    with open(file_name, 'r') as file:
        return int(file.readline().strip())
    
def receive_bpdu_package(data, interface, interfaces, switch_config, switch_id):
    
    global own_bridge_id
    global root_bridge_id
    global root_path_cost
    global root_port
    global is_root_bridge
    global switch_port
    
    dest_mac, bpdu_root_bridge_ID, received_bridge_ID, received_path_cost = parse_bpdu_packet(data)
    # this means we have to update the root_bridge of the switch because we found one switch better than this
    
    if bpdu_root_bridge_ID < root_bridge_id:
        root_bridge_id = bpdu_root_bridge_ID # we update the root_bridge_id with the new switch; we should return to update it
        root_path_cost = received_path_cost + 10 # we should return to update it
        root_port = interface # this is the interface were we received the bpdu package

        if is_root_bridge:
            # i have to set all trunk port except the root_port on designated
            for i in interfaces:
                if i != root_port and 'T' == switch_config[switch_id][i]:
                    switch_port[i] = 0 # i set the ports on blocking
                    
            is_root_bridge = False
        
        if switch_port[root_port] == 0:
            switch_port[root_port] = 1
            
        for i in interfaces:
            if 'T' == switch_config[switch_id][i]:
                create_bpdu_package(root_bridge_id, own_bridge_id, root_path_cost) # i send a BPDU package to all other ports
    
    elif bpdu_root_bridge_ID == root_bridge_id: # this means they have the same priotity of the root
        if root_port == interface and received_path_cost + 10 < root_path_cost:
            root_path_cost = received_path_cost + 10
        elif interface != root_port:
            if received_path_cost > root_path_cost:
                switch_port[interface] = 1 # i set the interface on designated
                    
    elif received_bridge_ID == own_bridge_id:
        switch_port[interface] = 0
    #else:
        # discard the package
    
    if own_bridge_id == root_bridge_id:
        for i in interfaces:
            switch_port[i] = 1 
        

own_bridge_id = None
root_bridge_id = None
root_path_cost = None
root_port = None
is_root_bridge = None
switch_port = {}

def main():
    
    # global switch_id
    global own_bridge_id
    global root_bridge_id
    global root_path_cost
    global root_port
    global is_root_bridge
    global switch_port
    # global interfaces
    
    # init returns the max interface number. Our interfaces
    # are 0, 1, 2, ..., init_ret value + 1
    switch_id = sys.argv[1] 
    mac_table = {}

    #initialize the interfaces
    own_bridge_id = priority_switch(switch_id)
    root_bridge_id = own_bridge_id # at the beggining each switch has the root_bridge own id
    root_path_cost = 0
    root_port = -1
    is_root_bridge = True

    num_interfaces = wrapper.init(sys.argv[2:]) # number of interfaces the switch has
    interfaces = range(0, num_interfaces)
    #interfaces are the form of: 1, 2, 3
    # get_name_interface(I) is the form of r-0

    print("# Starting switch with id {}".format(switch_id), flush=True)
    print("[INFO] Switch MAC", ':'.join(f'{b:02x}' for b in get_switch_mac()))
    
    # each port of the switch it will be or designated or blocked
    # a blocked port is marked with 0
    # a designated (listening) port will be 1
    switch_config = {}
    switch_config[switch_id] = {}
    # Printing interface names
    for i in interfaces:
        switch_port[i] = 1 # i set every port on designated
        switch_config[switch_id][i] = identify_vlan_id(switch_id, i)
    
    # Create and start a new thread that deals with sending BDPU
    t = threading.Thread(target=send_bdpu_every_sec, args=(interfaces, switch_config, switch_id))
    t.start()

    while True:
        # Note that data is of type bytes([...]).
        # b1 = bytes([72, 101, 108, 108, 111])  # "Hello"
        # b2 = bytes([32, 87, 111, 114, 108, 100])  # " World"
        # b3 = b1[0:2] + b[3:4].

        #interface - on what interface the packege was received
        #data - the content of the packege
        # every second if we are toot bridge we have to send bpdu package

        interface, data, length = recv_from_any_link() 
        
        dest_mac, src_mac, ethertype, vlan_id = parse_ethernet_header(data)

        # Print the MAC src and MAC dst in human readable format
        dest_mac = ':'.join(f'{b:02x}' for b in dest_mac)
        src_mac = ':'.join(f'{b:02x}' for b in src_mac)

        # Note. Adding a VLAN tag can be as easy as

        print(f'Destination MAC: {dest_mac}')
        print(f'Source MAC: {src_mac}')
        print(f'EtherType: {ethertype}')

        print("Received frame of size {} on interface {}".format(length, interface), flush=True)

        # TODO: Implement forwarding with learning
        # dest_mac - destinatia mac
        # src_mac - soursa mac
        # interface - portul de pe care a fost primit pachetul

        if dest_mac == "01:80:c2:00:00:00":
            receive_bpdu_package(data, interface, interfaces, switch_config, switch_id)
        else: 
            mac_table[src_mac] = interface # asociez adresa mac cu portul
            if not dest_mac in mac_table: # it doesnt exist in mac_table so we have to send on broadcast on the same VLAN
                forward_vlan_broadcast(vlan_id, interfaces, interface, switch_id, length, data, switch_config, switch_port)
            else:
                forward_package(vlan_id, switch_id, mac_table[dest_mac], mac_table[src_mac], length, data, switch_config, switch_port)

        # TODO: Implement VLAN support
   

        # TODO: Implement STP support

        # data is of type bytes.
        # send_to_link(i, length, data)

if __name__ == "__main__":
    main()