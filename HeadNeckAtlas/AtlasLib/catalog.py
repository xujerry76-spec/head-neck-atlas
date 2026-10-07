TASKS = {'head_glands_cavities': '头部腺体与腔隙', 'head_muscles': '头部肌肉'}
STRUCTURES = {
    'eye_left': ('左眼球', 'head_glands_cavities'),
    'eye_right': ('右眼球', 'head_glands_cavities'),
    'parotid_gland_left': ('左腮腺', 'head_glands_cavities'),
    'parotid_gland_right': ('右腮腺', 'head_glands_cavities'),
    'masseter_left': ('左咬肌', 'head_muscles'),
    'masseter_right': ('右咬肌', 'head_muscles'),
}


def display_name(name):
    return STRUCTURES.get(name, (name, None))[0]
