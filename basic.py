usernames = {}
def get_info():
    username = input("Enter username :")
    password = input("Enter password :")
    if username not in usernames.keys():
        name = input("Enter display name:").capitalize()
        usernames["username"] = name
    print(usernames)
get_info()

    