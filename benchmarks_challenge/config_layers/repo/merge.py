def resolve(defaults, file_config, overrides):
    result = defaults
    for layer in (file_config, overrides):
        for key,value in layer.items():
            if value: result[key]=value
    return result
