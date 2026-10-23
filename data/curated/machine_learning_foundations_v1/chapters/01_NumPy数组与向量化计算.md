# NumPy 数组与向量化计算

> 课程：机器学习基础与实践  \n> 上游来源：[nyandwi-machine-learning-complete](https://github.com/Nyandwi/machine_learning_complete/blob/8aabb071866027dd5c83de6de0c82a17f2ebe79e/docs/01_intro_to_Numpy_for_data_computation.ipynb)  \n> 固定版本：`8aabb071866027dd5c83de6de0c82a17f2ebe79e`  \n> 上游文件：`docs/01_intro_to_Numpy_for_data_computation.ipynb`  \n> 许可证：MIT，Copyright (c) 2021 Jean de Dieu Nyandwi  \n> 转换说明：Notebook 未执行，所有执行输出与单元元数据均已移除。

## 本章目标

理解数组形状、索引、广播与向量化，为数值特征处理建立基础。

## 精选教材内容

<table align="left">
  <td>
    <a href="https://colab.research.google.com/github/nyandwi/machine_learning_complete/blob/main/1_data_computations_with_numpy/1_intro_to_numpy_for_data_computation.ipynb" target="_parent"><img src="https://colab.research.google.com/assets/colab-badge.svg" alt="Open In Colab"/></a>
  </td>
  <td>
</table>

*This notebook was created by [Jean de Dieu Nyandwi](https://twitter.com/jeande_d) for the love of machine learning community. For any feedback, errors or suggestion, he can be reached on email (johnjw7084 at gmail dot com), [Twitter](https://twitter.com/jeande_d), or [LinkedIn](https://linkedin.com/in/nyandwi).*

<a name='0'></a>
# Intro to NumPy for Data Computations

This is lab is performing data computations with NumPy. NumPy is a scientific tool used to make mathematical computations easily. 

In this lab, you will learn to:

 * [1. Create a NumPy array](#1)
 * [2. Select data: indexing and slicing of array](#2)
 * [3. Perform mathematical and other basic operations](#3)
 * [4. Perform basic statistics](#4)
 * [5. Manipulate data](#5)

If you are using Google Colab, we do not need to install NumPy. We will only have to import it just like this:

`import numpy as np`

If you are using local Jupyter notebooks, make sure you have it installed already.

<a name='1'></a>
## 1. Creating an Array in NumPy

Array can either be vector or matrice. A vector is one dimensional array, and a matrix is a two or more dimensional array.

```python
## Importing numpy

import numpy as np
```

```python
## Creating a simple 1 dimensional array: vector
np.array([1,2,3,4,5])
```

```python
## Creating 2 dimensional array: matrix

np.array([(1,2,3,4,5), (6,7,8,9,10)])
```

```python
## Creating an array from a list

num_list = [1,2,3,4,5]

np.array(num_list)
```

```python
print(np.array(num_list))
```

### 1.1 Generating Array

NumPy offers various options to generate an array depending on particular need, such as:

* Generating identity array
* Generating zero array of a given size
* Generating ones array with a given size
* Generating an array in a given range
* Generating an array with random values

```python
## Generating an identity array 

identity_array = np.identity(4)
print(identity_array)
```

```python
## Generating an identity matrix of 1s

np.eye(4)
```

```python
# You can multiply with any constant

np.eye(4) * 7
```

```python
# Generating zero array of a given size
# 1 dimensional zero array
np.zeros(5)
```

```python
# Creating two dimensional array: pass the tuple of rows and columns' number
#np.zeros((rows, columns))

np.zeros((5,6))
```

```python
# Generating ones array of a given size
# 1 dimensional one array

np.ones(5)
```

```python
# Creating two dimensional ones array: pass the tuple of rows and columns' number
# np.ones((rows, columns))

np.ones((5,6))
```

```python
## Generating an array in a given range or interval

np.arange(0,5)
```

```python
## If you want to control the step size

np.arange(0,20,2)
```

```python
## You can also use linspace to generate an evenly spaced numbers in a given interval

np.linspace(0,20,5)
```

```python
np.linspace(0,100,5)
```

```python
np.linspace(0,10,10)
```

```python
## Generating an array with random values
# Create a 1D array with 4 random numbers

np.random.rand(4)
```

```python
np.random.rand(4)

#We will not get teh same values
```

```python
np.random.rand(4,5)
```

```python
### Generate one random integer in a given range

np.random.randint(5,50)
```

```python
### Generate 10 random integers in a given range

np.random.randint(5,50,10)
```

```python
## Random see to output the same random vaues at all run time 
import random

random.seed(10)

random.randint(5,50)
```

<a name='2'></a>
## 2. Data Selection: Indexing and slicing an Array

Indexing: Selecting individual elements from the array

Slicing: Selecting group of element from the array.

### 2.1 1D Array Indexing and Selection

```python
# Creating a 1 dimensional vector

array_1d = np.array([1,2,3,4,5])
```

```python
## Indexing: selcting an element from an array

array_1d[1]
```

```python
array_1d [-1]
```

```python
# Slicing: Returning the grou of element from an array

array_1d [2:4]
```

### 2.2 2D Array Indexing and Selection

```python
## Indexing 2D array

array_2d = np.array([[1,2,3],[4,5,6],[7,8,9]])
```

```python
## Selecting individual element
## array_2d[row][column]
## let's select 5..that is row 1, column 1 (we start from 0!!)

array_2d[1][1]
```

```python
# let's select 9..that is row 2, column 2

array_2d[2][2]
```

```python
## Selecting whole row
#array_2d[row]

array_2d[1]
```

```python
## Selecting group of elements in 2D array
## array_2d[rows, columns]..You select rows and columns

## Let's select the first two rows
## Rows :2 denotes that we are selecting all rows up to the second. 
## Columns : denotes that all columns are selected.


array_2d[:2,:]
```

```python
## Selecting all first two rows and first two columns

array_2d[:2,0:2]
```

```python
## Above is same as

array_2d[0:2,:]
```

```python
## This will return all rows, and so all columns and so same as orginal array
array_2d[0:3,:]
```

```python
## return the second row

array_2d[2,:]
```

```python
## return the second column

array_2d[:,2]
```

```python
## return the last two columns

array_2d[:,1:3]
```

```python
## return the first column

array_2d[:,0]
```

```python
## return the first row

array_2d[0,:]
```

Indexing or selecting 2D array may seems confusing but when you try it multiple times, you get the idea. If you are selecting an entire row, that means the all the columns are selected (but not their all values). And vice versa. 

As shown below, we are selecting the first row, but as you can see all columns are selected (:).

```
array_2d[0,:]
```

### 2.3 Conditional selection

You can use a condition to select values in an array. Let's use comparison operators to select the values.

```python
## Let's create an array

arr= np.array(([1,2,3],[4,5,6],[7,8,9]))
```

```python
## Select all elements in an array which are less than 6

arr[arr <6 ]
```

```python
## Select all elements in an array which are greater than 6

arr[arr > 6]
```

```python
## Select all even numbers in an array

arr[arr % 2 ==0 ]
```

```python
## Select all odd numbers in an array

arr[arr % 2 !=0 ]
```

```python
## You can also have multiple conditions

## In all odd numbers, return values which are greater or equal to 5


arr[(arr % 2 !=0 ) & (arr >=5) ]
```

```python
## Using logical selection, you can also return True for values in which a given condition is met in an array

arr > 5
```

```python
## We do not have 0 in our array

arr == 0
```

<a name='3'></a>
## 3. Basic Array Operations

### 3.1 Quick Arithmetic operation: Addition, Subtraction, Multiplication, Division, Squaring

```python
# Let's create two arrays

arr1 = np.arange(0,5)
arr2 = np.arange(6,11)
```

```python
## Addition

arr1 + arr2
```

```python
## Subtraction

arr2 - arr1
```

```python
## Multiplication

arr1 * arr2
```

```python
## Division

arr1 / arr2
```

```python
## Squaring

arr1 ** 2
```

### 3.2 Universal functions

NumPy universal functions (`ufunc`) allows to compute math, trigonometric, logical and comparison operations such as sin, cos, tan, exponent(exp), log, square, greater, less, etc...

```python
## creating two arrays 

arr1 = np.arange(0,5)
arr2 = np.arange(6,11)
```

```python
## Calculating the sum of two arrays

np.add(arr1, arr2)
```

```python
## Calculating the product of two arrays

np.multiply(arr1, arr2)
```

```python
## Calculating the difference between two arrays

np.subtract(arr1, arr2)
```

```python
## Calculating the division of two arrays

np.divide(arr1, arr2)
```

```python
## Calculating the sin of arr1

np.sin(arr1)
```

```python
np.sin([0,45,90,180])
```

```python
## Calculating the cosine of arr 1

np.cos(arr1)
```

```python
np.cos([0,45,90,180])
```

```python
## Calculating the tangent(tan) of the array

np.tan(arr2)
```

```python
## Calculating the logarithmic(log) of the array

np.log(arr2)
```

```python
## Calculating the exponent(exp or e^) of the array

np.exp(arr2)
```

```python
## Calculating the power  of the array
## Array 1 is powered array 2...0^6=0, 1^7=1, 2^8=256, etc..

np.power(arr1, arr2)
```

```python
## Comparison operations return true or false
## Arr 1 is less than arr 2...so that's false

np.greater(arr1, arr2)
```

```python
## Comparison operations return true or false
## Arr 1 is less than arr 2...so that's true

np.less(arr1, arr2)
```

<a name='4'></a>
## 4. Basic Statistics

With NumPy, we can compute the basic statistics such as the standard deviation (std), variance (var),mean, median, minimum value, maximum value of an array. 

More about NumPy statistics: https://numpy.org/doc/stable/reference/routines.statistics.html#order-statistics

```python
## Creating an array 

arr = np.arange(0,5)
arr
```

### 4.1 Standard Deviation

```python
## calculating the standard deviation of the array
## Std is how much an element of the array deviates from the mean of the array

np.std(arr)
```

```python
arr2 = np.array([[3,4], [5,6]])

np.std(arr2)
```

```python
## Specifying the axis
## By default, the std is computed on the flattened values (or converted into a single column vector)

np.std(arr2, axis=0)
```

```python
np.std(arr2, axis=1)
```

### 4.2 Variance

```python
## Calculating the Variance (var)

arr = np.arange(0,5)

np.var(arr)
```

```python
np.var(arr2)
```

### 4.3 Mean

```python
## Calculating the mean of the array

np.mean(arr)
```

```python
## mean gives the same results as the average
np.average(arr)
```

### 4.4 Median

```python
## Calculating the median of the array

np.median(arr)
```

### 4.3 Minimum and Maximum

```python
## Calculating the minimum value

np.min(arr)
```

```python
## Calculating the maximum value

np.max(arr)
```

<a name='5'></a>
## 5. Data Manipulation

Data Manipulation is important step in Machine Learning project. Let's some of NumPy methods and functions which are useful in data manipulation.

### 5.1 Shape of the array

```python
## Creating an array 

arr1 = np.arange(0,10)
arr2 = np.array(([1,2,3],[4,5,6],[7,8,9]))
```

```python
arr1
```

```python
arr2
```

```python
np.shape(arr1)
```

```python
np.shape(arr2)
```

```python
arr2.shape
```

### 5.2 Shaping the Array

`np.reshape(array_name, newshape=(rows, columns)` or `array_name.reshape(rows, columns)` change the shape of the array. The rows and columns of the new shape has to comform with the existing data of the array. Otherwise, it won't work. Take an example, you can convert (3,3) array into (1,9) but you can't convert it into (5,5).

```python
### arr1 is (10,)....10 rows, 1 column. Let's reshape it into (5,2)
np.reshape(arr1, newshape=(5,2))
```

```python
## This would also work
arr1.reshape(5,2)
```

```python
arr2_reshaped = arr2.reshape(9,1)
arr2_reshaped.T
```

```python
arr2_reshaped.reshape(3,3)
```

```python
## np.resize can also be used to change the shape of the array into a specific size

np.resize(arr2, (1,9))
```

### 5.3 Copying array

```python
arr1 = np.arange(0,10)
arr1
```

```python
arr1_copy = arr1.copy()
arr1_copy
```

```python
## Copying the values of one array into the other 

## Let's copy array 2 into 1 --they have the same shape

arr1 = np.arange(0,6)
arr2 = np.arange(6,12)
```

```python
## arr1 is destination, arr2 is source
np.copyto(arr1, arr2)
```

```python
arr1
```

### 5.4 Joining arrays

```python
### Creating two arrays

arr1 = np.array([[1,2,3],[4,5,6],[7,8,9]])
arr2 = np.array([[10,11,12]])
```

```python
## Joining them

np.concatenate((arr1, arr2))
```

```python
## Transposing arr2
## arr2.T is transpose operation

np.concatenate((arr1, arr2.T), axis=1)
```

```python
### Setting axis to none flatten the array

np.concatenate((arr1, arr2), axis=None)
```

```python
### Joining two 1Ds array into 2D array: Stacking

# Column stacking

arr1 = np.arange(0,6)
arr2 = np.arange(6,12)

np.column_stack((arr1, arr2))
```

```python
## Row stacking 

np.row_stack((arr1, arr2))
```

### 5.5 Splitting arrays

```python
arr1 = np.arange(0,6)
arr1
```

```python
### Splitting the array into two arrays

np.split(arr1, 2)
```

```python
### Splitting the array into three arrays

np.split(arr1, 3)
```

### 5.6 Adding and repeating elements in an array

```python
arr1 = np.arange(0,6)
arr1
```

```python
## Adding the values at the end of the array
np.append(arr1,7)
```

```python
### Given an array, can you add itself multiple times? or repeat it?

arr = np.array([[1,2,3]])
np.tile(arr, 3)
```

```python
np.repeat(arr,3)
```

### 5.7 Sorting elements in an array

```python
arr = np.array([[1,2,3,4,5,3,2,1,3,5,6,7,7,5,9,5]])

np.sort(arr)
```

```python
## Finding the unique elements in an array

arr = np.array([[1,2,3,4,5,3,2,1,3,5,6,7,7,5,9,5]])

np.unique(arr)
```

### 5.8 Reversing an array

```python
## You can also flip the array

arr = np.array([[1,2,3],[4,5,6],[7,8,9]])
arr
```

```python
## Up/down flipping

np.flipud(arr)
```

```python
## left/right flipping

np.fliplr(arr)
```

---



---

That's it for NumPy. In this lab, you learned how to create an array, perform basic operations, and also how to manipulate an array. 


In the next lab, we will learn about the Pandas, another important tool used for real world data manipulation.

### [BACK TO TOP](#0)
