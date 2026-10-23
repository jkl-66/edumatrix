# K-Means 聚类

> 课程：机器学习基础与实践  \n> 上游来源：[nyandwi-machine-learning-complete](https://github.com/Nyandwi/machine_learning_complete/blob/8aabb071866027dd5c83de6de0c82a17f2ebe79e/docs/22_intro_to_unsupervised_learning_with_kmeans_clustering.ipynb)  \n> 固定版本：`8aabb071866027dd5c83de6de0c82a17f2ebe79e`  \n> 上游文件：`docs/22_intro_to_unsupervised_learning_with_kmeans_clustering.ipynb`  \n> 许可证：MIT，Copyright (c) 2021 Jean de Dieu Nyandwi  \n> 转换说明：Notebook 未执行，所有执行输出与单元元数据均已移除。

## 本章目标

理解无监督聚类目标、训练过程、结果解释和适用限制。

## 精选教材内容

<table align="left">
  <td>
    <a href="https://colab.research.google.com/github/nyandwi/machine_learning_complete/blob/main/6_classical_machine_learning_with_scikit-learn/10_intro_to_unsupervised_learning_with_kmeans_clustering.ipynb" target="_parent"><img src="https://colab.research.google.com/assets/colab-badge.svg" alt="Open In Colab"/></a>
  </td>
</table>

*This notebook was created by [Jean de Dieu Nyandwi](https://twitter.com/jeande_d) for the love of machine learning community. For any feedback, errors or suggestion, he can be reached on email (johnjw7084 at gmail dot com), [Twitter](https://twitter.com/jeande_d), or [LinkedIn](https://linkedin.com/in/nyandwi).*

<a name='0'></a>
# Intro to Unsupervised Learning - K-Means Clustering

K-Means clustering is a type of unsupervised learning algorithms. In unsupervised learning, the machine learning model do not get the labels during training. It instead has to figure out the labels itself. It's like learning without instructions. It's like a teacher telling you, "hey, here are 1000 exercises to use while preparing for a test, the test will be only 5 questions from all of those exercises." That can feel like a struggle, you will do all you can to narrow down these 100 exercises to 5. Some questions may be similar, or may be solved by one method, etc..the goal will merely be to narrow down the exercises, while maximizing the chance of passing the test. 

That type of example can be compared to clustering. The model is given bunch of data (lacking labels) and the job of the model is to find the labels that can be present according to the supplied data. 


K-Means Clustering require the number of clusters to be specified before training. The way this type of algorithm works is beyond the scope of this notebook but here are 3 main steps of how such algorithm work: 

* K-Means will randomly assigns samples of data to initial centroids of all clusters. This step is called initialization. A centroid is also referred to as a cluster center and it is the mean of all the sample of data in a cluster. 

* It then reassigns the samples to the nearest centroids.
* It also find the new centroids of all clusters by taking the mean value of all of the samples assigned to each previous centroids. 

The last two steps are repeated until the stopping criterion is fulfilled or when difference between the old and new centroids is constant. 

Unspervised learning has got its applications in areas such as grouping web search results, customer segmentation, news aggregation and more.

## KMeans Clustering

### Contents

* [1 - Imports](#1)
* [2 - Loading the data](#2)
* [3 - Exploratory Analysis](#3)
* [4 - Preprocessing the data](#4)
* [5 - Trainin K-Means Clustering to Find Clusters](#5)
* [6 - Evaluating K-Means Clustering](#6)
* [7 - Final Notes](#7)

<a name='1'></a>
## 1 - Imports

```python
import numpy as np
import pandas as pd
import seaborn as sns
import sklearn
import matplotlib.pyplot as plt
%matplotlib inline
```

<a name='2'></a>

## 2 - Loading the data

In this notebook, we will use a different dataset. Up to this point creating these notebooks, my goal has been to look on the other side, to try something new, to try new a dataset. If you have went through some notebooks about other algorithms, no doubt that you have learned something new or perhaps nothing new but you experienced a new dataset. 

In this notebook, we will use a mushroom dataset. The dataset describes mushrooms in terms of their physical characteristics and they are classified into: poisonous or edible.

The dataset also includes descriptions of hypothetical samples corresponding to 23 species of gilled mushrooms in the Agaricus and Lepiota Family. Each species is identified as definitely edible, definitely poisonous, or of unknown edibility and not recommended. This latter class was combined with the poisonous one. The Guide clearly states that there is no simple rule for determining the edibility of a mushroom; no rule like `leaflets three, let it be for Poisonous Oak and Ivy.`

The dataset contains the labels (edibility) but for the purpose of doing clustering, we will remove the labels.

```python
# Let's firs hide warnings just in case

import warnings
warnings.filterwarnings('ignore')
```

```python
from sklearn.datasets import fetch_openml

mushroom_data = fetch_openml(name='mushroom', version=1)
```

```python
mushroom_data.data.shape
```

As you can see above, there are 8124 examples and 22 features.

```python
# Description of the data 
print(mushroom_data.DESCR)
```

```python
# Displaying feature names

mushroom_data.feature_names
```

```python
# Displaying target name

mushroom_data.target_names
```

```python
# Getting the whole dataframe

mushroom_data = mushroom_data.frame
```

<a name='3'></a>
## 3 - Exploratory Data Analysis

### Taking a quick look into the dataset

```python
mushroom_data.head()
```

```python
# Displaying the last rows 

mushroom_data.tail()
```

```python
mushroom_data.info()
```

All features are categorical. So we will make sure to handle them.

### Checking Summary Statistics

```python
# Summary stats

mushroom_data.describe()
```

### Checking Missing Values

```python
# Checking missing values

mushroom_data.isnull().sum()
```

It seems that we have missing values in the feature `stalk-root`. 

Usually there are three things to do with if them if they are present:
* We can remove all missing values completely
* We can leave them as they are or
* We can fill them with a given strategy such as mean, media or most frequent value. Either `Sklearn` or Pandas provides a quick ways to fill these kind of values. 

We will handle that during the data preprocessing.

### More Data Exploration

Before preprocessing the data, let's take a look into specific features. 

I want to also make note that I do not know alot about mushrooms. I thought that it would be interesting to use this real world datasets, and perhaps some people who will come across this may some of mushroom samples and their characteristics.

```python
plt.figure(figsize=(12,7))
sns.countplot(data=mushroom_data, x='cap-shape', hue='class')
```

In cap_shape, the letters stands for: `ell=b,conical=c,convex=x,flat=f, knobbed=k,sunken=s`. It seems that the convex type is dominant and most of it are edible.

```python
plt.figure(figsize=(12,7))

sns.countplot(data=mushroom_data, x='cap-color', hue='class')
```

The above is the cap color. The alphabets stands for `brown=n,buff=b,cinnamon=c,gray=g,green=r,pink=p,purple=u,red=e,white=w,yellow=y `. 

Also it seems that most caps are brown(n), either edible or brown.

```python
plt.figure(figsize=(12,7))

sns.countplot(data=mushroom_data, x='population')
```

The most populations are most several. Here are what the letters stand for: `abundant=a,clustered=c,numerous=n, scattered=s,several=v,solitary=y`.

```python
plt.figure(figsize=(12,7))

sns.countplot(data=mushroom_data, x='habitat')
```

```python
plt.figure(figsize=(12,7))

sns.countplot(data=mushroom_data, x='stalk-root')
```

Above is the feature that is missing values. We will remove all missing values. Since the missing values are of one category, we will drop it to avoid adding noise in the dataset.

And finally, we can look in the class feature. There are two categories, `e(edible)` and `p(poisonous)`.

```python
plt.figure(figsize=(12,7))

sns.countplot(data=mushroom_data, x='class')
```

<a name='4'></a>

## 4 - Data Preprocessing

Let's remove the missing values first.

```python
mushroom_df = mushroom_data.dropna()
```

For the purpose of performing clustering, we will remove the labels.

```python
mushroom = mushroom_df.drop('class', axis=1)
mushroom_labels = mushroom_df['class']
```

Let's now convert all categorical features into the numerics.

```python
from sklearn.preprocessing import OrdinalEncoder

encoder = OrdinalEncoder()

mushroom_prepared = encoder.fit_transform(mushroom)
```

```python
mushroom_prepared
```

As you can see above, `mushroom_prepared` is a NumPy array. We can convert it back to the Pandas Dataframe although KMeans algorithm can accept both as input.

```python
mushroom_prep_df = pd.DataFrame(mushroom_prepared, columns=mushroom.columns)
mushroom_prep_df.head()
```

No alphabets anymore. They were perfectly encoded or converted to numerics representation.

We are now ready to find the labels with KMeans Clustering. Again, this is for the assumption that we do not have labels, or to make it simple, we have a data about the characteristics of different plants, but we do not know if they are edible or not. We want to use unsupervised learning to figure that out.

<a name='5'></a>

## 5 - Training K-Means Clustering to Find Clusters

We are going to create a KMeans model from `sklearn.cluster`. We will remember to provide the number of the clusters, which is 2 in our case.

```python
from sklearn.cluster import KMeans

k_clust = KMeans(n_clusters=2, random_state=42)

k_clust.fit(mushroom_prep_df)
```

We can access the cluster centers by `model.cluster_centers_`.

```python
k_clust.cluster_centers_
```

Also, we can get the labels that the KMeans provided for each data point.

```python
k_labels = k_clust.labels_
k_labels
```

<a name='6'></a>

### 6 -Evaluating K-Means Clustering

In real world, evaluating the performance of KMeans is not an easy thing, because there are not true labels to compare with the clustered labels. In our case since we have them, we can find things like accuracy score, or even find the confusion matrix to display the actual and predicted classes. Not to mention classification report to find things like Recall, Precision, or F1 Score. 

But again since we are merely comparing the labels(true and clustered), we do not need that extra metrics. 

Before finding the accuracy score, I will first convert the true labels into the numbers or encode them. For simplicity, I will use a map function.

```python
map_dict = {
    
    'p':0,
    'e':1
}

mushroom_labels_prep = mushroom_labels.map(map_dict)
```

```python
mushroom_labels_prep
```

```python
from sklearn.metrics import accuracy_score

accuracy_score(mushroom_labels_prep, k_labels)
```

This is not excellent, but it's so impressive. Why? Well, KMeans never saw the labels, it was only feed the data of different characteristics of poisonous and edible mushrooms and its job was to try to find patterns in the data so as to learn if a given mushroom specy is a poisonous or edible. 


KMeans algorithm is very useful in areas where you have a bunch of unlabeled data. Take an example in customer segmentation. You may want to provide different promotions to some groups of your customers but you have no clue of who would benefit from that particular promotion. So, you can try to find the group of customers using this algorithm. It will try to group similar customers according to their interests, and will likely appreciate the promotion.

The same concept can be applied to grouping the equipments that has similar defects in an industry. That was just mentioning few, there are more applications of KMeans clustering.

<a name='7'></a>

### 7 - Final Notes

In this notebook, we learned the idea behind unsupervised learning and KMeans clustering. We also practiced that on mushroom dataset where we were interested in grouping the species that can be poisonous or edible. 

If you like mushrooms and you know some of their characteristics, no doubt that you enjoyed this notebook. Maybe pick one edible sample and make it your next meal :)

## [BACK TO TOP](#0)
