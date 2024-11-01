import ctypes
import sys
from ctypes import create_string_buffer

# dlink.so este biblioteca C pe care o folosim pentru a trimite cadre de nivel
# data link, aceasta se gaseste in directorul lib
lib = ctypes.CDLL('./dlink.so')

# Aici specificam semnatura functiilor pe care vrem sa le folosim din biblioteca dlink.
# De exemplu in C, functia recv_from_any_link arata astfel:
# int recv_from_any_link(char *frame_data, size_t *length)
# mai jos ctypes.c_char_p este echivalentul a unui char *
lib.recv_from_any_link.argtypes = (ctypes.c_char_p, ctypes.POINTER(ctypes.c_size_t))
lib.recv_from_any_link.restype = ctypes.c_int

lib.send_to_link.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_size_t)
lib.send_to_link.restype = ctypes.c_int

lib.init.argtypes = (ctypes.c_int, ctypes.POINTER(ctypes.c_char_p))
lib.init.restype = ctypes.c_int

lib.get_interface_mac.argtypes = (ctypes.c_int, ctypes.POINTER(ctypes.c_uint8))
lib.get_interface_mac.restype = None

lib.get_interface_name.argtypes = [ctypes.c_int]
lib.get_interface_name.restype = ctypes.c_char_p

# Peste functiile de mai sus, definim urmatoarele functii in python pe care
# urmeaza sa le folosim implementarea noastra
def init(argv_p):
    # Get the command-line arguments using sys.argv
    print("Initializing the switch")
    argv = [arg.encode('utf-8') for arg in argv_p]  # Convert each argument to bytes

    # Convert the list to a ctypes array
    argc = len(argv)
    argv_array = (ctypes.c_char_p * argc)(*argv)
    # Call the hub init function
    num_int = lib.init(argc, argv_array)
    return num_int

def recv_from_any_link():
    # Create a buffer for the data to be written into
    buffer_size = 1600 # MAX_PACKET_LEN

    buffer = ctypes.create_string_buffer(buffer_size)
    # Create a ctypes variable for the length
    length = ctypes.c_size_t()

    # Call the C function
    result = lib.recv_from_any_link(buffer, ctypes.byref(length))

    return result, bytes(buffer.raw[:length.value]), length.value

# Receives an interface, a byte array and a length.
def send_to_link(interface, length, buffer):
    # Create a buffer for the data to be written into
    buffer_size = length
    # Make sure buffer is smaller than MAX_PACKET_LEN
    assert(buffer_size < 1600)
    
    c_buf = create_string_buffer(buffer)
    c_len = ctypes.c_size_t(buffer_size)

    # Call the C function
    result = lib.send_to_link(interface, c_buf, c_len)

def get_switch_mac():
    # Create a buffer for the MAC address
    mac_buffer = (ctypes.c_uint8 * 6)()
    
    # Call the get_inferface mac function.
    # Our switch should have only 1 MAC and such
    # we return the MAC from interface 0
    lib.get_interface_mac(1, mac_buffer)
    
    return bytes(mac_buffer)

# Returns the name of an interface, used for the VLAN subtask
def get_interface_name(interface):

    return lib.get_interface_name(interface).decode('utf-8')
