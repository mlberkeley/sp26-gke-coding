def binary_search(arr, target):
    """
    Search for target in a sorted list.

    Return its index, or -1 if not found.
    """
    low, high = 0, len(arr) - 1
    while low <= high:
        mid = (low + high) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            high = mid - 1  # BUG: should be low = mid + 1
        else:
            low = mid + 1  # BUG: should be high = mid - 1
    return -1
