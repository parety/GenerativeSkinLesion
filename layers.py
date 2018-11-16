import torch
import torch.nn as nn
import torch.nn.functional as F

#----------------------------------------------------------------------------
# Equalized learning rate.

class EqualizedConv2d(nn.Module):
    def __init__(self, in_features, out_features, kernel_size, stride, padding):
        super(EqualizedConv2d, self).__init__()
        self.conv = nn.Conv2d(in_features, out_features, kernel_size, stride, padding, bias=True)
        nn.init.kaiming_normal_(self.conv.weight, a=nn.init.calculate_gain('conv2d'))
        nn.init.constant_(self.conv.bias, val=0.)
        # conv_w = self.conv.weight.data.clone()
        self.scale = self.conv.weight.data.pow(2.).mean().sqrt()
        self.conv.weight.data.copy_(self.conv.weight.data / self.scale)
    def forward(self, x):
        return self.conv(x.mul(self.scale))

class EqualizedLinear(nn.Module):
    def __init__(self, in_features, out_features):
        super(EqualizedLinear, self).__init__()
        self.linear = nn.Linear(in_features, out_features)
        nn.init.kaiming_normal_(self.linear.weight, a=nn.init.calculate_gain('linear'))
        nn.init.constant_(self.linear.bias, val=0.)
        # linear_w = self.linear.weight.data.clone()
        self.scale = self.linear.weight.data.pow(2.).mean().sqrt()
        self.linear.weight.data.copy_(self.linear.weight.data/self.scale)
    def forward(self, x):
        N = x.size(0)
        return self.linear(x.view(N,-1).mul(self.scale))

#----------------------------------------------------------------------------
# Minibatch standard deviation.
# reference: https://github.com/tkarras/progressive_growing_of_gans/blob/master/networks.py#L127

class MinibatchStddev(nn.Module):
    def __init__(self, group_size=4):
        super(MinibatchStddev, self).__init__()
        self.group_size = group_size
    def forward(self, x):
        G = min(self.group_size, x.size(0))
        M = x.size(0) / G
        s = x.size()
        y = torch.reshape(x, (G, M, x.size(1), x.size(2), x.size(3)))     # [GMCHW] Split minibatch into M groups of size G.
        y = y - torch.mean(y, dim=0, keepdim=True)                        # [GMCHW] Subtract mean over group.
        y = torch.mean(y.pow(2.), dim=0, keepdim=False)                   # [MCHW]  Calc variance over group.
        y = torch.sqrt(y + 1e-8)                                          # [MCHW]  Calc stddev over group.
        y = torch.mean(y.view(M,-1), dim=1, keepdims=False).view(M,1,1,1) # [M111]  Take average over fmaps and pixels.
        y = y.repeat(G,1,x.size(2), x.size(3))                            # [N1HW]  Replicate over group and pixels.
        return torch.cat([x, y], 1)                                       # [NCHW]  Append as new fmap.

#----------------------------------------------------------------------------
# Pixelwise feature vector normalization.
# reference: https://github.com/tkarras/progressive_growing_of_gans/blob/master/networks.py#L120

class PixelwiseNorm(nn.Module):
    def __init__(self):
        super(PixelwiseNorm, self).__init__()
    def forward(self, x):
        y = torch.mean(x.pow(2.), dim=1, keepdim=True) + 1e-8 # [N1HW]
        return x.div(y.sqrt())

#----------------------------------------------------------------------------
# Smoothly fade in the new layers.

class ConcatTable(nn.Module):
    def __init__(self, layer1, layer2):
        super(ConcatTable, self).__init__()
        self.layer1 = layer1
        self.layer2 = layer2
    def forward(self,x):
        return [self.layer1(x), self.layer2(x)]

class Fadein(nn.Module):
    def __init__(self, alpha=0.):
        super(Fadein, self).__init__()
        self.alpha = alpha
    def update_alpha(self, delta):
        self.alpha = self.alpha + delta
        self.alpha = max(0, min(self.alpha, 1.0))
    def get_alpha(self):
        return self.alpha
    def forward(self, x):
        # x is a ConcatTable, with x[0] being old layer, x[1] being the new layer to be faded in
        return x[0].mul(1.0-self.alpha) + x[1].mul(self.alpha)

#----------------------------------------------------------------------------
class Flatten(nn.Module):
    def __init__(self):
        super(Flatten, self).__init__()
    def forward(self, x):
        return x.view(x.size(0), -1)

#----------------------------------------------------------------------------
# Nearest-neighbor upsample

class Upsample(nn.Module):
    def __init__(self):
        super(Upsample, self).__init__()
    def forward(self, x):
        return F.interpolate(x, scale_factor=2, mode='nearest')
