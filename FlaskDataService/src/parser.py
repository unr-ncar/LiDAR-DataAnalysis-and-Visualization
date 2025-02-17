# ----------------------------------------------------------------------------------------
#
#   Point Cloud Parser Script
#
#   Authors: Andrew Munoz, Chase Carthen
#   Date: 06/15/2021
#   Purpose: Takes in LiDAR point cloud data and parses through the data.
#            Reads through PCD file and passes cleaned data to a pandas
#            dataframe which is then returned to app.py.
#
# ----------------------------------------------------------------------------------------

import re
import struct
import warnings
import datetime
import json

import numpy as np
import pandas as pd

# PCD Header Mapping to numpy type
numpy_pcd_type_mappings = [(np.dtype('float32'), ('F', 4)),
                           (np.dtype('float64'), ('F', 8)),
                           (np.dtype('uint8'), ('U', 1)),
                           (np.dtype('uint16'), ('U', 2)),
                           (np.dtype('uint32'), ('U', 4)),
                           (np.dtype('uint64'), ('U', 8)),
                           (np.dtype('int16'), ('I', 2)),
                           (np.dtype('int32'), ('I', 4)),
                           (np.dtype('int64'), ('I', 8))]
numpy_type_to_pcd_type = dict(numpy_pcd_type_mappings)
pcd_type_to_numpy_type = dict((q, p) for (p, q) in numpy_pcd_type_mappings)

# Function that parses header objects
def parse_header(lines): 
    
    # Dictionary to store metadata found in the header 
    metadata = {
        'objects': []
    }

    # Boolean used to search for object coordinates
    searchSwitch = False

    # Begin looping through .pcd header
    for ln in lines:
        if ln.startswith('#') or len(ln) < 2:
            continue
        print(ln)
        if not ln.startswith('end') and searchSwitch:
            coordinates = ln.split(' ')
            positions = {}
            print(coordinates)
            positions['minx'] = float(coordinates[0])
            positions['maxx'] = float(coordinates[1])
            positions['miny'] = float(coordinates[2])
            positions['maxy'] = float(coordinates[3])
            positions['minz'] = float(coordinates[4])
            positions['maxz'] = float(coordinates[5])
            positions['class'] = 'Object'
            metadata['objects'].append(positions)
        match = re.match('(\w+)\s+([\w\s\.\/]+)', ln)
        if not match:
            warnings.warn("warning: can't understand line: %s" % ln)
            continue
        # Check for each key found in the header 
        key, value = match.group(1).lower(), match.group(2)
        if key == 'version':
            metadata[key] = value
        elif key in ('fields', 'type'):
            metadata[key] = value.split()
        elif key in ('size', 'count'):
            metadata[key] = map(int, value.split())
        elif key in ('width', 'height', 'points'):
            metadata[key] = int(value)
        elif key == 'viewpoint':
            metadata[key] = map(float, value.split())
        elif key == 'data':
            metadata[key] = value.strip().lower()
        elif key == 'minx': #object position values
            searchSwitch = True
        elif key == 'topic':
            metadata[key] = value
        elif key == 'time':
            metadata[key] = value
        elif key == 'end':
            searchSwitch = False
    if 'count' not in metadata:
        metadata['count'] = [1] * len(metadata['fields'])
    if 'viewpoint' not in metadata:
        metadata['viewpoint'] = [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0]
    if 'version' not in metadata:
        metadata['version'] = '.7'
    print(metadata.get('topic','None'))
    return metadata

""" Function builds numpy structured array dtype from the pcl metadata.
NOTE: Fields with count > 1 are 'flattened' by creating multiple single-count fields.
TODO: allow 'proper' multi-count fields."""
def build_dtype(metadata):
    fieldnames = []
    typenames = []
    for f, c, t, s in zip(metadata['fields'],
                          metadata['count'],
                          metadata['type'],
                          metadata['size']):
        np_type = pcd_type_to_numpy_type[(t, s)]
        if c == 1:
            fieldnames.append(f)
            typenames.append(np_type)
        else:
            fieldnames.extend(['%s_%04d' % (f, i) for i in range(c)])
            typenames.extend([np_type] * c)

    dtype = np.dtype(list(zip(fieldnames, typenames)))
    return dtype

""" Reads in pcd file and return the elements as pandas Dataframes.
Parameters (content: str - Path to the pcd file, isfilename: bool).
Returns a pandas Dataframe."""
def read_pcd(content, isfilename=False): 
    # Initialize data dictionary to store all the cleaned data
    data = {}

    # Initialize json dictionary
    jsondict = {}

    # Loops through pcd file
    if isfilename:
     with open(content, 'rb') as f:
        header = []
        # Loops through header to get metadata values
        while True:
            ln = f.readline().strip().decode()
            header.append(ln)
            if ln.startswith('DATA'):
                metadata = parse_header(header)
                dtype = build_dtype(metadata)
                break
        while True:
            ln = f.readline().strip().decode()
            if ln.startswith("Time"):
                break
        if metadata['data'] == 'ascii':
            pc_data = np.loadtxt(f, dtype=dtype, delimiter=' ')

        elif metadata['data'] == 'binary':
            rowstep = metadata['points'] * dtype.itemsize
            # for some reason pcl adds empty space at the end of files
            buf = f.read(rowstep)

            pc_data = np.fromstring(buf, dtype=dtype)

        elif metadata['data'] == 'binary_compressed':
            raise NotImplementedError("Go ask PCD why they use lzf compression.")
            # compressed size of data (uint32)
            # uncompressed size of data (uint32)
            # compressed data
            # junk
            fmt = 'II'
            compressed_size, uncompressed_size =\
                struct.unpack(fmt, f.read(struct.calcsize(fmt)))
            compressed_data = f.read(compressed_size)
            # TODO what to use as second argument? if buf is None
            # (compressed > uncompressed)
            # should we read buf as raw binary?
            if len(buf) != uncompressed_size:
                raise Exception('Error decompressing data')
            
            # Data is stored field-by-field
            pc_data = np.zeros(metadata['width'], dtype=dtype)
            ix = 0
            for dti in range(len(dtype)):
                dt = dtype[dti]
                bytes = dt.itemsize * metadata['width']
                column = np.fromstring(buf[ix:(ix + bytes)], dt)
                pc_data[dtype.names[dti]] = column
                ix += bytes
    
    else: 
        header = []
        lines = content.split(b'\n')

        for ln in lines:
            header.append(ln.decode())

            if ln.startswith(b'DATA'):
                metadata = parse_header(header)
                dtype = build_dtype(metadata)
            elif ln.startswith(b'Time '):
                metadata = parse_header(header)
                topic_value = str(metadata['topic'])
                time_value = int(metadata['time'])
                print(topic_value)
                minutes_cal = time_value/6e7
                minute = int(minutes_cal)
                break

        skip = content.find(b'Time ')
        skip = skip + content[skip:].find(b'\n')+1
        rowstep = metadata['points'] * dtype.itemsize
        if metadata['data'] == 'ascii':
            pc_data = np.fromstring(content[skip:], dtype=dtype, delimiter=' ')

        elif metadata['data'] == 'binary':
            #rowstep = metadata['points'] * dtype.itemsize
            # for some reason pcl adds empty space at the end of files
            #buf = f.read(rowstep)

            pc_data = np.fromstring(content[skip:], dtype=dtype)

        elif metadata['data'] == 'binary_compressed':
            raise NotImplementedError("Go ask PCD why they use lzf compression.")
            # compressed size of data (uint32)
            # uncompressed size of data (uint32)
            # compressed data
            # junk
            fmt = 'II'
            compressed_size, uncompressed_size =\
                struct.unpack(fmt, f.read(struct.calcsize(fmt)))
            compressed_data = f.read(compressed_size)
            # TODO what to use as second argument? if buf is None
            # (compressed > uncompressed)
            # should we read buf as raw binary?
            #buf = lzf.decompress(compressed_data, uncompressed_size)
            if len(buf) != uncompressed_size:
                raise Exception('Error decompressing data')
            
            # Data is stored field-by-field
            pc_data = np.zeros(metadata['width'], dtype=dtype)
            ix = 0
            for dti in range(len(dtype)):
                dt = dtype[dti]
                bytes = dt.itemsize * metadata['width']
                column = np.fromstring(buf[ix:(ix + bytes)], dt)
                pc_data[dtype.names[dti]] = column
                ix += bytes
    
    # Pass in parsed point cloud data to pandas dataframe
    df = pd.DataFrame(pc_data)

    # Create color string and check if dataframe contains color info
    col = 'rgb'
    if col in df.columns:
        # get the 'rgb' column from dataframe
        packed_rgb = df.rgb.values
        # 'rgb' values are stored as float in dataframe. Values converted to int using numpy
        packed_rgb = packed_rgb.astype(np.float32).tostring()
        packed_rgb = np.frombuffer(packed_rgb, dtype=np.int32)

        # Values unpacked into 'red', 'green' and 'blue' indices
        df['red'] = np.asarray((packed_rgb >> 16) & 255, dtype=np.uint8)
        df['green'] = np.asarray((packed_rgb >> 8) & 255, dtype=np.uint8)
        df['blue'] = np.asarray(packed_rgb & 255, dtype=np.uint8)

        # Remove packed rgb from dataframe as it is no longer needed
        df.drop(col, axis=1, inplace=True)

    # Cleaned data stored in data dictionary
    data['topic'] = topic_value
    data['time'] = str(minute)
    data['points'] = df.to_json(index = False, orient = 'split')
    data['objects'] = metadata['objects']

    # Convert Pandas dataframe vertices values into a json dictionary 
    jsondict['x'] = list(df['x'])
    jsondict['y'] = list(df['y'])
    jsondict['z'] = list(df['z'])
    jsondict['intensity'] = list(df['intensity'])
    data["points"] = json.dumps(json.loads(json.dumps(jsondict), parse_float=lambda x: round(float(x), 2)))

    # Returns clean data dictionary to main Flask app
    return data