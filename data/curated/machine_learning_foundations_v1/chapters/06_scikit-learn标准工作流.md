# scikit-learn 标准工作流

> 课程：机器学习基础与实践  \n> 上游来源：[nyandwi-machine-learning-complete](https://github.com/Nyandwi/machine_learning_complete/blob/8aabb071866027dd5c83de6de0c82a17f2ebe79e/docs/12_intro_to_sklearn.ipynb)  \n> 固定版本：`8aabb071866027dd5c83de6de0c82a17f2ebe79e`  \n> 上游文件：`docs/12_intro_to_sklearn.ipynb`  \n> 许可证：MIT，Copyright (c) 2021 Jean de Dieu Nyandwi  \n> 转换说明：Notebook 未执行，所有执行输出与单元元数据均已移除。

## 本章目标

掌握估计器、fit/predict、数据划分和常用训练接口。

## 精选教材内容

<table align="left">
  <td>
    <a href="https://colab.research.google.com/github/nyandwi/machine_learning_complete/blob/main/6_classical_machine_learning_with_scikit-learn/0_intro_to_sklearn.ipynb" target="_parent"><img src="https://colab.research.google.com/assets/colab-badge.svg" alt="Open In Colab"/></a>
  </td>
</table>

*This notebook was created by [Jean de Dieu Nyandwi](https://twitter.com/jeande_d) for the love of machine learning community. For any feedback, errors or suggestion, he can be reached on email (johnjw7084 at gmail dot com), [Twitter](https://twitter.com/jeande_d), or [LinkedIn](https://linkedin.com/in/nyandwi).*

# Intro to Scikit-Learn for Shallow Machine Learning

Scikit-Learn (aka sklearn) is a simple, beautifull and well designed machine learning library. 

Scikit-Learn provides various learning algorithms. Using them is as simple as filling a cup of coffee. 

Beyond learning algorithms, the library also provides data processing functions which are also very simple to use. In addition to those processing functions, Scikit-Learn offers other functions such as pipelines, model tuning, and much more. 

To learn more about Scikit-Learn, check out its [website](https://scikit-learn.org/stable/). It's to navigate and you will immediately see how well designed it is. 

To practice how simple Scikit-Learn is, let's build a simple linear regressor. Our goal is to fit a line. 


We will start with imports, in this case, we will import `Linear Regressor` from sklearn linear models. We will also imports `NumPy` which we will use to create our sample data and `Matplotlib` to plot the created data.

```python
from sklearn.linear_model import LinearRegression
import numpy as np
import matplotlib.pyplot as plt
```

After we have imported Linear Regressor, we will create our data. It's a numpy array, `X` and `y`. If you are too quick to crunch the numbers, you are going to see that the X and y represent a linear equation `y=2X+1`.

```python
X = np.array([[1.0],[2.0],[3.0],[4.0],[5.0],[6.0],[7.0],[8.0]], dtype='float')
y = np.array([[3.0],[5.0],[7.0],[9.0],[11.0],[13.0],[15.0],[17.0]], dtype='float')
```

Like we said, here is the relationship between X and y. It is a line.

```python
plt.plot(X,y)
```

Now that we have created the data, it's time to create a model.

```python
model =  LinearRegression()
```

That was simple. Next, we are going to train the model. Using `fit`method, we are going to pass the input data `X` and output data `y`. `y` is also referred to as a label.

```python
model.fit(X, y)
```

Huum, that was quick. Now the model is trained on the dataset. Let's try to see how confident it is on the data it never saw. We will create a test array having the numbers from 9 to 11, just to test if the predictions will be 19, 21, 23 respectively. Let's do that!!

```python
test_array = np.array([[9.0],[10.0],[11.0]], dtype='float')

model.predict(test_array)
```

As you can see, it did well. It was able to learn the relationship between X and y just from the data. This the what it means when we say that different to traditional programming which requires rules and data to give results, machine learning takes data and results and give the rules. 

Let's try to see the rules in our example.

```python
model.coef_
```

```python
model.intercept_
```

Great, the model was able to determine the exact linear equation that we used when creating the data. The `coef` is the `coefficient`, commonly known to `weight`. So in this case it is 2, and it what is multplied to the input data `X`. On the other hand, 1 is the `intercept`, commonly known to `bias`. Combining them we get our equation, `y=2X+1`. These two parameters (weights and biases) are the two output components of any machine learning model. 

In our case, since the data was so simple, it is easy to directly tell that the output is a linear equation, but when it comes to the real world scenarios, it may be hard because you have many features and data points. 


Hopefully this was a good introduction to Machine Learning with Scikit-Learn. We have not touched to the whole of what we can do with Scikit-Learn and in the next labs, you will see more models applied to the real world datasets!
