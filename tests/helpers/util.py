import os.path

def local_fpath(local_file, relpath):
    return os.path.join(os.path.dirname(local_file), relpath)
