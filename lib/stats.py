import math     # type: ignore

def mean_stddev(buff:list, count:int, startidx:int, ringlen:int)->tuple[float, float]:
    """
        Args:
            buff:   list of values, stored in a ring buffer
            count:  number of values to use
            startidx: position in ring to begin at... and then...
            look BACKWARDS from ABSOLUTE index startidx... NOT relative to hf_index

        Returns:
            tuple containg mean and sample std deviation
    """
    if count > ringlen:     # ooh - that's bad...
        print(f"mean_stddev: Count {count} reduced to {ringlen}")
        count = ringlen     # should probably raise an exception...
    if count < 2:
        return 0, 0
    s = 0.0
    for i in range(count):
        mod_index = (startidx - 1 - i) % ringlen
        s += buff[mod_index]    
    mean: float = s / count

    ss_diffs = 0.0
    for i in range(count):
        mod_index = (startidx - 1 - i) % ringlen
        x = buff[mod_index]
        diff = (x - mean)
        ss_diffs += diff * diff
    v = ss_diffs / (count - 1)
    sd = math.sqrt(v)
    return mean, sd

def linear_regression(x: list, y: list, count:int, startidx:int, ringlen:int) -> tuple[float, float, float, float]:
    """
    Calculate linear regression coefficients (slope, intercept) and other stats (std dev and r-squared).
    
    Args:
        x: List of x values
        y: List of y values
        count: how many values to go BACKWARDS
        startidx: absolute index of start of sample data in ring buffer.  NOT relative to buffer index !!
        ringlen: length of ring buffer
        
    Returns:
        Tuple of (slope, intercept, std deviation, r-squared)
    """
    xcount = len(x)
    if xcount != len(y) or xcount < 2:
        raise ValueError("x and y must have same length and length >= 2")
        
 # Now... make it work round a ring buffer, not a straight list
 # Also... look backwards, simulating previous n readings
    ring_xbar = ring_ybar = 0.0
    my_x = count
    for i in range(count):
        my_x -= 1
        mod_idx = (startidx - i) % ringlen
        # xi = x[mod_idx]
        # yi = y[mod_idx]
        ring_xbar += my_x
        ring_ybar += y[mod_idx]

    x_mean = ring_xbar / count
    y_mean = ring_ybar / count

    sum_xy = sum_xx = sum_yy = 0.0
    ss_res = ss_tot = 0.0  # For R-squared calculation

    my_x = count
    for i in range(count):
        my_x -= 1
        mod_idx = (startidx - i) % ringlen
        # xi = x[mod_idx]
        # yi = y[mod_idx]

        # Differences from means
        dx = my_x - x_mean
        dy = y[mod_idx] - y_mean
        
        # Sums for regression
        sum_xy += dx * dy
        sum_xx += dx * dx
        sum_yy += dy * dy

    if sum_xx == 0:
        raise ValueError("x values must not all be equal")
    
    # Calculate regression coefficients
    slope = sum_xy / sum_xx
    intercept = y_mean - slope * x_mean

    # print(f'{mod_idx=:2}  {xi=}, {yi=:.1f}')
    # num = sum((xi - x_mean) * (yi - y_mean) for i in range(n))
    # den = sum((xi - x_mean) ** 2 for i in range(n))
    # std_dev = math.sqrt(sum((yi - y_mean) * (yi - y_mean) for i in range(n))) / (n-1)
    
    # Calculate R-squared
    my_x = count

    for i in range(count):
        my_x -= 1
        mod_idx = (startidx - i) % ringlen
        # xi = x[mod_idx]
        yi = y[mod_idx]
        
        # Predicted y value
        # y_pred = slope * x[mod_idx] + intercept
        y_pred = slope * my_x + intercept
        # 
        # print(f'{xi} {y_pred} {yi}')
        # Sum of squares of residuals
        ss_res += (y_pred - y_mean) ** 2
        # Total sum of squares
        ss_tot += (yi - y_mean) ** 2
    
    r_squared = (ss_res / ss_tot) if ss_tot != 0 else 0
    std_dev = math.sqrt(sum_yy / (count-1))  # Using sum_yy we calculated earlier
    
    # print(f'{x_mean=} {y_mean=} {sum_xy=} {sum_xx=}')
    return slope, intercept, std_dev, r_squared