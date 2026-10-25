def ratio_text_to_number(supported_ratio):
    supported_ratio_list = [int(i) for i in supported_ratio.split(':')]
    return supported_ratio_list[0] / supported_ratio_list[1]
