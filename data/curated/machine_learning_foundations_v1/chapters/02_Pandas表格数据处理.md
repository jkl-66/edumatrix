# Pandas 表格数据处理

> 课程：机器学习基础与实践  \n> 上游来源：[nyandwi-machine-learning-complete](https://github.com/Nyandwi/machine_learning_complete/blob/8aabb071866027dd5c83de6de0c82a17f2ebe79e/docs/02_data_manipulation_with_pandas.ipynb)  \n> 固定版本：`8aabb071866027dd5c83de6de0c82a17f2ebe79e`  \n> 上游文件：`docs/02_data_manipulation_with_pandas.ipynb`  \n> 许可证：MIT，Copyright (c) 2021 Jean de Dieu Nyandwi  \n> 转换说明：Notebook 未执行，所有执行输出与单元元数据均已移除。

## 本章目标

掌握表格数据读取、选择、变换、聚合和连接的标准工作流。

## 精选教材内容

<table align="left">
  <td>
    <a href="https://colab.research.google.com/github/Nyandwi/machine_learning_complete/blob/main/2_data_manipulation_with_pandas/2_data_manipulation_with_pandas.ipynb" target="_parent"><img src="https://colab.research.google.com/assets/colab-badge.svg" alt="Open In Colab"/></a>
  </td>
  <td>
</table>

*This notebook was created by [Jean de Dieu Nyandwi](https://twitter.com/jeande_d) for the love of machine learning community. For any feedback, errors or suggestion, he can be reached on email (johnjw7084 at gmail dot com), [Twitter](https://twitter.com/jeande_d), or [LinkedIn](https://linkedin.com/in/nyandwi).*

<a name='0'></a>
# Data Manipulation with Pandas

 In this lab, you will learn how to manipulate data with Pandas. Here is an overview:

* [1. Basics of Pandas for data manipulation:](#1)

     * [A. Series and DataFrames](#1-1)
     * [B. Data Indexing and Selection, and Iteration](#1-2)
     * [C. Dealing with Missing data](#1-3)
     * [D. Basic operations and Functions](#1-4)
     * [E. Aggregation Methods](#1-5)
     * [F. Groupby](#1-6)
     * [G. Merging, Joining and Concatenate](#1-7)
     * [H. Beyond Dataframes: Working with CSV, and Excel](#1-8)
     
* [2. Real World Exploratory Data Analysis (EDA)](#2)

<a name='1'></a>
## 1. Basics of Pandas for data manipulation

<a name='1-1'></a>
### A. Series and DataFrames

Both series and DataFrames are Pandas Data structures. 

Series is like one dimensional NumPy array with axis labels.

DataFrame is multidimensional NumPy array with labels on rows and columns. 

Working with NumPy, we saw that it supports numeric type data. Pandas on other hand supports whole range of data types, from numeric to strings, etc..

Since we are using python notebook, we do not need to install Pandas. We only just have to import it. 

```
import pandas as pd
```

```python
# importing numpy and pandas

import numpy as np
import pandas as pd
```

#### Creating Series

Series can be created from a Python list, dictionary, and NumPy array.

```python
# Creating the series from a Python list

num_list = [1,2,3,4,5]

pd.Series(num_list)
```

```python
week_days = ['Mon','Tues','Wed','Thur','Fri']

pd.Series(week_days, index=["a", "b", "c", "d", "e"])
```

Note the data types `int64` and `object`.

```python
# Creating the Series from dictionary 

countries_code = { 1:"United States",
                 91:"India",
                 49:"Germany",
                 86:"China",
                250:"Rwanda"}

pd.Series(countries_code)
```

```python
d = {1:'a', 2:'b', 3:'c', 4:'d'}
pd.Series(d)
```

```python
# Creating the Series from NumPy array
# We peovide the list of indexes
# if we don't provide the indexes, the default indexes are numbers...starts from 0,1,2..

arr = np.array ([1, 2, 3, 4, 5])
pd.Series(arr)
```

```python
pd.Series(arr, index=['a', 'b', 'c', 'd', 'e'])
```

#### Creating DataFrames

DataFrames are the most used Pandas data structure. It can be created from a dictionary, 2D array, and Series.

```python
# Creating DataFrame from a dictionary

countries = {'Name': ['USA', 'India', 'German', 'Rwanda'], 
             
             'Codes':[1, 91, 49, 250] }

pd.DataFrame(countries)
```

```python
# Creating a dataframe from a 2D array
# You pass the list of columns

array_2d = np.array ([[1,2,3], [4,5,6], [7,8,9]])

pd.DataFrame(array_2d, columns = ['column 1', 'column 2', 'column 3'])
```

```python
# Creating a dataframe from Pandas series 
# Pass the columns in a list

countries_code = { "United States": 1,
                 "India": 91,
                 "Germany": 49,
                 "China": 86,
                 "Rwanda":250}

pd_series = pd.Series (countries_code)

pd.Series(countries_code)

df = pd.DataFrame(pd_series, columns = ['Codes'])
df
```

```python
# Adding a column
# Number in population are pretty random

df ['Population'] = [100, 450, 575, 5885, 533]

df
```

```python
# Removing a column 

df.drop('Population', axis =1)
```

```python
df.columns
```

```python
df.keys
```

```python
df.index
```

<a name='1-2'></a>
### B. Data Indexing, Selection and Iteration

Indexing and selection works in both Series and Dataframe.

Because DataFrame is made of Series, let's focus on how to select data in DataFrame.

```python
# Creating DataFrame from a dictionary

countries = {'Name': ['USA', 'India', 'German', 'Rwanda'], 
             
             'Codes':[1, 91, 49, 250] }

df = pd.DataFrame(countries, index=['a', 'b', 'c', 'd'])
df
```

```python
df['Name']
```

```python
df.Name
```

```python
df ['Codes']
```

```python
## When you have many columns, columns in list will be selected

df [['Name', 'Codes']]
```

```python
# This will return the first two rows
df [0:2]
```

You can also use `loc` to select data by the label indexes and `iloc` to select by default integer index (or by the position of the row)

```python
df.loc['a']
```

```python
df.loc['b':'d']
```

```python
df [:'b']
```

```python
df.iloc[2]
```

```python
df.iloc[1:3]
```

```python
df.iloc[2:]
```

### Conditional Selection

```python
df
```

```python
#Let's select a country with code 49

df [df['Codes'] ==49 ]
```

```python
df [df['Codes'] < 250 ]
```

```python
df [df['Name'] =='USA' ]
```

```python
# You can use and (&) or (|) for more than conditions
#df [(condition 1) & (condition 2)]

df [(df['Codes'] == 91 ) & (df['Name'] == 'India') ]
```

You can also use `isin()` and `where()` to select data in a series or dataframe.

```python
# isin() return false or true when provided value is included in dataframe
sample_codes_names=[1,3,250, 'USA', 'India', 'England']

df.isin(sample_codes_names)
```

As you can see, it returned `True` wherever a country code or name was found. Otherwise, `False`. You can use a dictinary to match search by columns. A key must be a column and values are passed in list.

```python
sample_codes_names = {'Codes':[1,3,250], 'Name':['USA', 'India', 'England']}

df.isin(sample_codes_names)
```

```python
df2 = pd.DataFrame(np.array ([[1,2,3], [4,5,6], [7,8,9]]), 
                   columns = ['column 1', 'column 2', 'column 3'])

df2
```

```python
df2.isin([0,3,4,5,7])
```

```python
df2 [df2 > 4]
```

```python
df2.where(df2 > 4)
```

`where` allows you to replace the values that doesn't meet the provided condition with any other value. So, if we do `df2.where(df2 > 4, 0)` as follows, all values less than `4` will be replaced by `0`.

```python
df2.where(df2 > 4, 0)
```

Similarly, we can achieve the above by...

```python
df2 [df2 <= 4] = 0
df2
```

### Iteration

```
df.items() #Iterate over (column name, Series) pairs.
df.iteritems() Iterate over (column name, Series) pairs.
DataFrame.iterrows() Iterate over DataFrame rows as (index, Series) pairs.
DataFrame.itertuples([index, name]) Iterate over DataFrame rows as namedtuples.
```

```python
# Iterate over (column name, Series) pairs.

for col_name, content in df2.items():
    print(col_name)
    print(content)
```

```python
# Iterate over (column name, Series) pairs.
# Same as df.items()

for col_name, content in df2.iteritems():
    print(col_name)
    print(content)
```

```python
# Iterate over DataFrame rows as (index, Series) pairs

for row in df2.iterrows():
    print(row)
```

```python
# Iterate over DataFrame rows as namedtuples

for row in df2.itertuples():
    print(row)
```

Notes: Thanks to [Prit Kalariya](https://twitter.com/pritkalariya) for Contributing the Iteration part!

<a name='1-3'></a>
### C. Dealing with Missing data

Real world datasets are messy, often with missing values. Pandas replace NaN with missing values by default. NaN stands for not a number. 

Missing values can either be ignored, droped or filled.

```python
# Creating a dataframe

df3 = pd.DataFrame(np.array ([[1,2,3], [4,np.nan,6], [7,np.nan,np.nan]]), 
                   columns = ['column 1', 'column 2', 'column 3'])
```

#### Checking Missing values

```python
# Recognizing the missing values

df3.isnull()
```

```python
# Calculating number of the missing values in each feature

df3.isnull().sum()
```

```python
# Recognizng non missig values

df3.notna()
```

```python
df3.notna().sum()
```

#### Removing the missing values

```python
## Dropping missing values 

df3.dropna()
```

All rows are deleted because dropna() will remove each row which have missing value.

```python
# you can drop NaNs in specific column(s)

df3['column 3'].dropna()
```

```python
# You can drop data by axis 
# Axis = 1...drop all columns with Nans
# df3.dropna(axis='columns')

df3.dropna(axis=1)
```

```python
# axis = 0...drop all rows with Nans
# df3.dropna(axis='rows') is same 

df3.dropna(axis=0)
```

#### Filling the missing values

```python
# Filling Missing values

df3.fillna(10)
```

```python
df3.fillna('fillme')
```

```python
# You can forward fill (ffill) or backward fill(bfill)
# Or fill a current value with previous or next value

df3.fillna(method='ffill')
```

```python
# Won't change it because the last values are NaNs, so it backward it

df3.fillna(method='bfill')
```

```python
# If we change the axis to columns, you can see that Nans at row 2 and col 2 is backfilled with 6

df3.fillna(method='bfill', axis='columns')
```

<a name='1-4'></a>
### D. More Operations and Functions

This section will show the more and most useful functions of Pandas.

```python
df4 = pd.DataFrame({'Product Name':['Shirt','Boot','Bag'], 
              'Order Number':[45,56,64], 
              'Total Quantity':[10,5,9]}, 
              columns = ['Product Name', 'Order Number', 'Total Quantity'])
```

#### Retrieving basic info about the Dataframe

```python
# Return a summary about the dataframe

df4.info()
```

```python
# Return dataframe columns

df4.columns
```

```python
# Return dataframe data

df4.keys
```

```python
# Return the head of the dataframe ....could make sense if you have long frame
# Choose how many rows you want in head()

df4.head(1)
```

```python
# Return the tail of the dataframe

df4.tail(1)
```

```python
# Return NumPy array of the dataframe

df4.values
```

```python
# Return the size or number of elements in a dataframe

df4.size
```

```python
# Return the shape

df4.shape
```

```python
# Return the length of the dataframe/the number of rows in a dataframe

df4.shape[0]
```

```python
# Return the length of the dataframe/the number of columns in a dataframe

df4.shape[1]
```

#### Unique Values

```python
# Return unique values in a given column 

df4['Product Name'].unique()
```

```python
# Return a number of unique values
df4['Product Name'].nunique()
```

```python
# Counting the occurence of each value in a column 

df4['Product Name'].value_counts()
```

#### Applying a Function to Dataframe

```python
# Double the quantity product

def double_quantity(x):
  return x * x
```

```python
df4['Total Quantity'].apply(double_quantity)
```

```python
# You can also apply an anonymous function to a dataframe
# Squaring each value in dataframe

df5 = pd.DataFrame([[1,2], [4,5]], columns=['col1', 'col2'])

df5.applymap(lambda x: x**2)
```

#### Sorting values in dataframe

```python
# Sort the df4 by the order number

df4.sort_values(['Order Number'])
```

```python
df4.sort_values(['Order Number'], ascending=False)
```

<a name='1-5'></a>
### E. Aggregation Methods

```python
df4
```

```python
# summary statistics

df4.describe()
```

```python
df4.describe().transpose()
```

```python
# Mode of the dataframe
# Mode is the most recurring values

df4['Total Quantity'].mode()
```

```python
# The maximum value

df4['Total Quantity'].max()
```

```python
# The minimum value

df4['Total Quantity'].min()
```

```python
# The mean

df4['Total Quantity'].mean()
```

```python
# The median value in a dataframe

df4['Total Quantity'].median()
```

```python
# Standard deviation

df4['Total Quantity'].std()
```

```python
# Variance 

df4['Total Quantity'].var()
```

```python
# Sum of all values in a column

df4['Total Quantity'].sum()
```

```python
# Product of all values in dataframe

df4['Total Quantity'].prod()
```

<a name='1-6'></a>
### F. Groupby

`Group by` involves splitting data into groups, applying function to each group, and combining the results.

```python
df4 = pd.DataFrame({'Product Name':['Shirt','Boot','Bag', 'Ankle', 'Pullover', 'Boot', 'Ankle', 'Tshirt', 'Shirt'], 
              'Order Number':[45,56,64, 34, 67, 56, 34, 89, 45], 
              'Total Quantity':[10,5,9, 11, 11, 8, 14, 23, 10]}, 
              columns = ['Product Name', 'Order Number', 'Total Quantity'])
```

```python
df4
```

```python
# Let's group the df by product name

df4.groupby('Product Name').mean()
```

```python
df4.groupby('Product Name').sum()
```

```python
df4.groupby('Product Name').min()
```

```python
df4.groupby('Product Name').max()
```

```python
df4.groupby(['Product Name', 'Order Number']).max()
```

```python
df4.groupby(['Product Name', 'Order Number']).sum()
```

You can also use `aggregation()` after groupby.

```python
df4.groupby('Product Name').aggregate(['min', 'max', 'sum'])
```

<a name='1-7'></a>
### G. Combining Datasets: Concatenating, Joining and Merging

#### Concatenation

```python
# Creating dataframes

df1 = pd.DataFrame({'Col1':['A','B','C'],
                   'Col2':[1,2,3]}, 
                   index=['a','b','c'])

df2 = pd.DataFrame({'Col1':['D','E','F'],
                   'Col2':[4,5,6]}, 
                   index=['d','e','f'])


df3 = pd.DataFrame({'Col1':['G','I','J'],
                   'Col2':[7,8,9]}, 
                   index=['g', 'i','j'])
```

```python
df1
```

```python
df2
```

```python
df3
```

```python
# Concatenating: Adding one dataset to another

pd.concat([df1, df2, df3])
```

The default axis is `0`. This is how the combined dataframes will look like if we change the `axis to 1`.

```python
pd.concat([df1, df2, df3], axis=1)
```

```python
# We can also use append()

df1.append([df2, df3])
```

#### Merging

If you have worked with SQL, what `pd.merge()` does may be familiar. It links data from different sources (different features) and you have a control on the structure of the combined dataset.

*Pandas Merge method(`how`): SQL Join Name : Description*



```
* left : LEFT OUTER JOIN : Use keys or columns from left frame only

* right : RIGHT OUTER JOIN : Use keys or columns from right frame only

* outer : FULL OUTER JOIN : Use union of keys or columns from both frames

* inner : INNER JOIN : Use intersection of keys or columns from both frames
```

```python
df1 = pd.DataFrame({'Name': ['Joe', 'Joshua', 'Jeanne', 'David'],
                        'Role': ['Manager', 'Developer', 'Engineer', 'Scientist']})

df2 = pd.DataFrame({'Name': ['David', 'Joshua', 'Joe', 'Jeanne'],
'Year Hired': [2018, 2017, 2020, 2018]})

df3 = pd.DataFrame({'Name': ['David', 'Joshua', 'Joe', 'Jeanne'],
'No of Leaves': [15, 3, 10, 12]})
```

```python
df1
```

```python
df2
```

```python
pd.merge(df1, df2)
```

```python
## Let's merge on Role being a key 

pd.merge(df1, df2, how='inner', on="Name")
```

```python
df1 = pd.DataFrame({'col1': ['K0', 'K0', 'K1', 'K2'],
                     'col2': ['K0', 'K1', 'K0', 'K1'],
                        'A': ['A0', 'A1', 'A2', 'A3'],
                        'B': ['B0', 'B1', 'B2', 'B3']})
    
df2 = pd.DataFrame({'col1': ['K0', 'K1', 'K1', 'K2'],
                               'col2': ['K0', 'K0', 'K0', 'K0'],
                                  'C': ['C0', 'C1', 'C2', 'C3'],
                                  'D': ['D0', 'D1', 'D2', 'D3']})
```

```python
df1
```

```python
df2
```

```python
pd.merge(df1, df2, how='inner', on=['col1', 'col2'])
```

```python
pd.merge(df1, df2, how='outer', on=['col1', 'col2'])
```

```python
pd.merge(df1, df2, how='left')
```

```python
pd.merge(df1, df2, how='right')
```

#### Joining

Joining is a simple way to combine columns of two dataframes with different indexes.

```python
df1 = pd.DataFrame({'Col1': ['A', 'B', 'C'],
                     'Col2': [11, 12, 13]},
                      index=['a', 'b', 'c']) 

df2 = pd.DataFrame({'Col3': ['D', 'E', 'F'],
                    'Col4': [14, 14, 16]},
                      index=['a', 'c', 'd'])
```

```python
df1
```

```python
df2
```

```python
df1.join(df2)
```

```python
df2.join(df1)
```

You can see that with `df.join()`, the alignment of data is on indexes.

```python
df1.join(df2, how='inner')
```

```python
df1.join(df2, how='outer')
```

Learn more about Merging, Joining, and Concatenating the Pandas Dataframes [here](https://pandas.pydata.org/docs/user_guide/merging.html).

<a name='1-8'></a>
### H. Beyond Dataframes: Working with CSV and Excel

In this last section of Pandas' fundamentals, we will see how to read real world data with different formats: CSV and Excel

#### CSV and Excel

Let's use california housing dataset.

```python
# Let's download the data 

!curl -O https://raw.githubusercontent.com/nyandwi/public_datasets/master/housing.csv
```

```python
data = pd.read_csv('housing.csv')
```

```python
data.head()
```

```python
type(data)
```

```python
## Exporting dataframe back to csv

data.to_csv('housing_dataset', index=False)
```

If you look into the folder sidebar, you can see `Housing Dataset`.

```python
## Exporting CSV to Excel

data.to_excel('housing_excel.xlsx', index=False)
```

```python
## Reading the Excel file back

excel_data = pd.read_excel('housing_excel.xlsx')
```

```python
excel_data.head()
```

<a name='2'></a>
## Real World: Exploratory Data Analysis (EDA)

All above was the basics. Let us apply some of these techniques to the real world dataset, `Red wine quality`.

```python
!curl -O https://raw.githubusercontent.com/nyandwi/public_datasets/master/winequality-red.csv
```

```python
wine_data = pd.read_csv('winequality-red.csv')
```

```python
# Displaying the head of the dataset

wine_data.head()
```

```python
# Displaying the tail of the dataset

wine_data.tail()
```

```python
# Displaying summary statistics

wine_data.describe().transpose()
```

```python
# Displaying quick information about the dataset 

wine_data.info()
```

```python
# Checking missing values

wine_data.isnull().sum()
```

```python
# wine quality range from 0 to 10. The higher the quality value, the good wine is

wine_data['quality'].value_counts()
```

```python
wine_data.groupby(['fixed acidity', 'volatile acidity', 'citric acid']).sum()
```

```python
wine_data.groupby(['free sulfur dioxide', 'total sulfur dioxide']).sum()
```

This is the end of the lab that was about using Pandas to manipulate data. Alot of things will make sense when we start to prepare data for machine learning models in the next notebooks.

<a name='0'></a>

### [BACK TO TOP](#0)
