import time
import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
import torch
import torch.nn as nn
import torch.nn.functional as F


## 设置一个随机种子，固定模型的随机性，用于确保机器学习和数据处理中结果的可复现性
def set_random_seed(state=1):
    """
        设定随机种子
    :param state: 随机种子值
    :return: None
    """
    gens = (np.random.seed, torch.manual_seed)
    for set_state in gens:
        set_state(state)


def process_data(data):
    """
        处理加载的训练数据DataFrame，去掉id，同时对signals以”，“进行拆分。
    :param data: DataFrame, shape(n, 3)
    :return: np array, shape(n, 206)
    """
    res = []
    for i in range(data.shape[0]):
        x_res = data.iloc[i, 1].split(',')   ## .iloc是pandas库中用于按位置选择行和列的方法，如data.iloc[:,:3]，提取所有行，前三列的数据。注：.split（）只用于单行，不能执行多行
        label = data.iloc[i, 2]
        x_res.append(label)
        res.append(x_res)
    return np.array(res, dtype=np.float64)  ## dtype=np.float64这个很关键，不然存在里面的是字符串，如“0.90”

## 此函数貌似没用到
def get_pred_x(data):
    """
        处理需要预测数据的DataFrame
    :param data: DataFrame, shape(n, 2)
    :return: np array, shape(n, 205)
    """
    res = []
    for i in range(data.shape[0]):
        x_res = data.iloc[i, 1].split(',')
        res.append(x_res)
    return np.array(res, dtype=np.float64)


def train_loop(dataloader, model, loss_fn, optimizer):
    """
        模型训练
    :param dataloader: 训练数据集
    :param model: 训练用到的模型
    :param loss_fn: 评估用的损失函数
    :param optimizer: 优化器
    :return: None
    """
    model.train()  ## 调用此函数时，模型进入训练模式，启用如Dropout、Batchnorm等功能
    for batch, x_y in enumerate(dataloader):
        X, y = x_y[:, :205].type(torch.float64), torch.tensor(x_y[:, 205], dtype=torch.long, device='cuda:0')   ## dtype = torch.long 将float32数据转换为int64数据类型(整数)
        with torch.set_grad_enabled(True):
            # Compute prediction and loss
            pred = model(X.float())
            loss = loss_fn(pred, y)
            optimizer.zero_grad()
            # Backpropagation
            loss.backward()
            optimizer.step()


def test_loop(dataloader, model, loss_fn):
    """
        模型测试部分
    :param dataloader: 测试数据集
    :param model: 测试模型
    :param loss_fn: 损失函数
    :return: None
    """
    size = len(dataloader.dataset)  ## dataloader.dataset为加载的数据集
    test_loss, correct, l1_loss = 0, 0, 0
    # 用来计算abs-sum. 等于PyTorch L1Loss
    l1loss_fn = AbsSumLoss()
    ## 调用torch.no_grad()函数，停止autograd模块的工作，起到加速和节省显存的作用
    with torch.no_grad(): 
        model.eval()  ## 调用此函数，模型进入评估模式，不启用BatchNorm和Dropout，参数不会更新
        for x_y in dataloader:
            X, y = x_y[:, :205].type(torch.float64), torch.tensor(x_y[:, 205], dtype=torch.long, device='cuda:0')
            # Y用来计算L1 loss, y是CrossEntropy loss.
            ## Y就是标签数据对应的one-hot码
            Y = torch.zeros(size=(len(y), 4), device='cuda:0')
            for i in range(len(Y)):
                Y[i][y[i]] = 1
            pred = model(X.float())
            test_loss += loss_fn(pred, y).item()                                ## 计算交叉熵损失
            l1_loss += l1loss_fn(pred, Y).item()                                ## 转为one-hot码后，计算abs-sum
            correct += (pred.argmax(1) == y).type(torch.float).sum().item()     ## 计算准确率

    test_loss /= size 
    correct /= size
    print(f"Test Results:\nAccuracy: {(100 * correct):>0.1f}% abs-sum loss: {l1_loss:>8f} CroEtr loss: {test_loss:>8f}")

## 此函数并未被调用
def prediction(net, loss):
    """
        对数据进行预测
    :param net: 训练好的模型
    :param loss: 模型的测试误差值, 不是损失函数. 可以去掉, 这里是用来给预测数据命名方便区分.
    :return: None
    """
    with torch.no_grad():
        net.eval()
        pred_loader = torch.utils.data.DataLoader(dataset=pred_data)
        res = []
        for x in pred_loader:
            x = torch.tensor(x, device='cuda:0', dtype=torch.float64)
            output = net(x.float())
            res.append(output.cpu().numpy().tolist())

        res = [i[0] for i in res]
        res_df = pd.DataFrame(res, columns=['label_0', 'label_1', 'label_2', 'label_3'])
        res_df.insert(0, 'id', value=range(120000, 140000))

        res_df.to_csv('CNN4-resB-final-loss ' + str(loss) + '.csv', index=False)


class Model(nn.Module):
    def __init__(self):
        super(Model, self).__init__()
        self.conv_layer1 = nn.Sequential(
            nn.Conv1d(in_channels=1, out_channels=16, kernel_size=3, padding=1),  # 16, 1, 205
            nn.BatchNorm1d(16),
            nn.ReLU()
        )

        self.conv_layer2 = nn.Sequential(
            nn.Conv1d(in_channels=16, out_channels=32, kernel_size=3, padding=1),
            nn.BatchNorm1d(32),
            nn.ReLU(),
            nn.AvgPool1d(kernel_size=5, stride=4),                                 # 32, 1, 51
        )

        self.conv_layer3 = nn.Sequential(
            nn.Conv1d(in_channels=32, out_channels=64, kernel_size=3, padding=1),  # 64, 1, 51
            nn.BatchNorm1d(64),
            nn.ReLU()
        )

        self.conv_layer4 = nn.Sequential(
            nn.Conv1d(in_channels=64, out_channels=128, kernel_size=3, padding=1),
            nn.BatchNorm1d(128),
            nn.ReLU(),
            nn.AvgPool1d(kernel_size=3, stride=2),                                 # 128, 1, 25
        )

        self.conv_layer5 = nn.Sequential(
            nn.Conv1d(in_channels=128, out_channels=256, kernel_size=3, padding=1),
            nn.BatchNorm1d(256),
            nn.ReLU()
        )

        self.conv_layer6 = nn.Sequential(
            nn.Conv1d(in_channels=256, out_channels=512, kernel_size=3, padding=1),
            nn.BatchNorm1d(512),
            nn.ReLU(),
            nn.AvgPool1d(kernel_size=3, stride=2),                                  # 512, 1, 12
        )

        self.full_layer = nn.Sequential(
            nn.Linear(in_features=512 * 12, out_features=512 * 12),
            nn.Dropout(0.5),
            nn.ReLU(),
            nn.Linear(in_features=512 * 12, out_features=512 * 12),
            nn.Dropout(0.5),
            nn.ReLU(),
            nn.Linear(in_features=512 * 12, out_features=4)
        )

        self.pred_layer = nn.Softmax(dim=1)

    def forward(self, x):
        x = x.unsqueeze(dim=1)
        x = self.conv_layer1(x)
        x = self.conv_layer2(x)
        x = self.conv_layer3(x)
        x = self.conv_layer4(x)
        x = self.conv_layer5(x)
        x = self.conv_layer6(x)
        x = x.view(x.size(0), -1)
        x = self.full_layer(x)

        if self.training:
            return x  ## 由于nn.CrossEntropyLoss()函数中已经集成了softmax层，因此在训练网络中，不需要再次添加softmax层，然后容易导致模型无法拟合；在测试过程中，由于不需要计算损失函数进行参数优化，因此需要添加softmax层
        else:
            return self.pred_layer(x)


class AbsSumLoss(nn.Module):
    def __init__(self):
        super(AbsSumLoss, self).__init__()

    def forward(self, output, target):
        loss = F.l1_loss(target, output, reduction='sum')

        return loss


if __name__ == '__main__':
    set_random_seed(1996)
    # 加载数据集
    data = pd.read_csv('train.csv')
    data = process_data(data)
    ## 下面两端构建的pred_data数据貌似并未用到
    pred_data = pd.read_csv('testB.csv')
    pred_data = get_pred_x(pred_data)

    # 初始化模型
    adm_lr = 1e-4
    sgd_lr = 5e-6
    mom = 0.8
    w_decay = 1e-5
    n_epoch = 100
    b_size = 64
    device = torch.device('cuda:0' if torch.cuda.is_available() else 'cpu')
    net = Model()
    net.to(device)
    optimizer = torch.optim.Adam(params=net.parameters(), lr=adm_lr, weight_decay=w_decay, amsgrad=True)
    loss_fn = nn.CrossEntropyLoss(reduction='sum')

    # 拆分训练测试集
    train, test = train_test_split(data, test_size=0.2) ## test_size表示测试集的占比
    train, test = torch.cuda.FloatTensor(train), torch.cuda.FloatTensor(test)
    train_loader = torch.utils.data.DataLoader(dataset=train, batch_size=b_size, shuffle=True)
    test_loader = torch.utils.data.DataLoader(dataset=test, batch_size=b_size)

    for epoch in range(n_epoch):
        if epoch == 20:
            optimizer = torch.optim.SGD(params=net.parameters(), lr=sgd_lr, weight_decay=w_decay, momentum=mom)
        start = time.time()
        print(f"\n----------Epoch {epoch + 1}----------")
        train_loop(train_loader, net, loss_fn, optimizer)
        test_loop(test_loader, net, loss_fn)
        end = time.time()
        print('training time: ', end - start)

    # predict
