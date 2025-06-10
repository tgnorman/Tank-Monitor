import math     # type: ignore

def mean_stddev(buff, buffidx:int, buflen:int, count:int)->tuple:
    if count < 2:
        return 0, 0
    s = 0.0
    for i in range(count):
        mod_index = (buffidx - i - 1) % buflen  # change to average hi_freq_kpa readings
        s += buff[mod_index]    
    mean: float = s / count

    ss = 0.0
    for i in range(count):
        mod_index = (buffidx - i - 1) % buflen  # change to average hi_freq_kpa readings
        x = buff[mod_index]
        d = (x - mean)
        ss += d * d
    v = ss / (count - 1)
    sd = math.sqrt(v)
    return mean, sd

def linear_regression(x: list, y: list, n:int, startidx:int, ringlen:int) -> tuple[float, float, float, float]:
    """Calculate linear regression coefficients (slope, intercept).
    
    Args:
        x: List of x values
        y: List of y values
        startidx: index of start of sample data in ring buffer
        
    Returns:
        Tuple of (slope, intercept, std deviation, r-squared)
    """
    n = len(x)
    if n != len(y) or n < 2:
        raise ValueError("x and y must have same length and length >= 2")
        
 # Now... make it work round a ring buffer, not a straight list
 # Also... look backwards, simulating previous n readings
    ring_xbar = ring_ybar = 0.0

    for i in range(n):
        mod_idx = (startidx - i - 1) % ringlen
        # xi = x[mod_idx]
        # yi = y[mod_idx]
        ring_xbar += x[mod_idx]
        ring_ybar += y[mod_idx]

    x_mean = ring_xbar / n
    y_mean = ring_ybar / n

    sum_xy = sum_xx = sum_yy = 0.0
    ss_res = ss_tot = 0.0  # For R-squared calculation

    for i in range(n):
        mod_idx = (startidx - i - 1) % ringlen
        # xi = x[mod_idx]
        # yi = y[mod_idx]

        # Differences from means
        dx = x[mod_idx] - x_mean
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
    for i in range(n):
        mod_idx = (startidx - i - 1) % ringlen
        # xi = x[mod_idx]
        yi = y[mod_idx]
        
        # Predicted y value
        y_pred = slope * x[mod_idx] + intercept
        
        # print(f'{xi} {y_pred} {yi}')
        # Sum of squares of residuals
        ss_res += (yi - y_pred) ** 2
        # Total sum of squares
        ss_tot += (yi - y_mean) ** 2
    
    r_squared = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0
    std_dev = math.sqrt(sum_yy / (n-1))  # Using sum_yy we calculated earlier
    
    return slope, intercept, std_dev, r_squared