import duckdb
import logging

import pandas as pd

from typing import List, Optional, Union

import pandas_market_calendars as mcal

logging.basicConfig(format='%(message)s ::: %(asctime)s', datefmt='%I:%M:%S %p')

#
# Adjusting pricing data
#

ADJUSTOR_FIELDS = {
    'crsp.security_daily': [
        {
            'adjustor': 'cfacpr',
            'fields_to_adjust': ['prc', 'openprc', 'askhi', 'bidlo', 'bid', 'ask'],
            'operation': '/',
            'function': 'abs'
        },
        {
            'adjustor': 'cfacshr',
            'fields_to_adjust': ['vol', 'shrout'],
            'operation': '*'
        }
    ]
}


def adjust_crsp_data(frame: pd.DataFrame) -> pd.DataFrame:
    """
    utility function to adjust CRSP pricing data.
    frame must have column "cfacpr" to adjust any price related column.
    frame must have column "cfacshr" to adjust and share related data
    configured to adjust: ['prc', 'openprc', 'askhi', 'bidlo', 'bid', 'ask', 'vol', 'shrout']

    Will make al columns lowe case!!!!!

    :param frame: the dataframe with the pricing data to adjust
    :return: passed frame with the pricing data adjusted
    """
    frame = frame.copy()
    frame.columns = [col.lower() for col in frame.columns]

    adjustment = '\n'.join([_adjust_field(field=col, table='crsp.security_daily') for col in frame.columns])

    if adjustment == '':
        logging.warning('NO COLUMNS ADJUSTED')
        return frame

    return frame.eval(adjustment)


def _adjust_field(field: str, table: str) -> str:
    """
    Makes the pandas eval string to adjust a given field.
    If there's no adjustment to be done then it will just return an empty string
    :param field: the single field we want to adjust
    :param table: the table the field is apart of
    """
    table_adj = ADJUSTOR_FIELDS.get(table.lower())

    if table_adj is None:
        raise ValueError(f'Table {table} is not in ADJUSTOR_FIELDS. '
                         f'Valid tables are {list(ADJUSTOR_FIELDS.keys())}')

    for diff_adj in table_adj:
        fields_to_adjust = diff_adj.get('fields_to_adjust')
        function = diff_adj.get('function')
        wanted_diff_adj = field in fields_to_adjust

        if wanted_diff_adj and function:
            return (f'{field} = {diff_adj["function"]}({field} {diff_adj["operation"]} '
                    f'{diff_adj["adjustor"]})')

        if wanted_diff_adj:
            return f'{field} = {field} {diff_adj["operation"]} {diff_adj["adjustor"]}'

    return ''


#
# Adjusting data for universe
#

class ConstituteAdjustment:
    """
    provides the functionality of correctly identifying on what day which asset should be in/not in the data set based
    on given constitute data
    """

    def __init__(self, id_col: str = 'symbol', date_type: str = 'timestamp'):
        """
        constructor for ConstituteAdjustment
        :param id_col: the asset identifier column for the data that will be passed
        :param date_type: should the date be outputted as a pd.Period or a pd.Timestamp?
        self.__index_constitutes_factor: holds the index constitutes for the factor in a MultiIndex of date,
            self.__id_col
        self.__index_constitutes_pricing: holds the index constitutes for the pricing in a MultiIndex of date,
            self.__id_col
        """
        self.__id_col = id_col

        if date_type not in ['period', 'timestamp']:
            raise ValueError(f'{date_type} is not recognised')
        self.__date_type = date_type

        self.__index_constitutes_factor: Optional[pd.MultiIndex] = None
        self.__index_constitutes_pricing: Optional[pd.MultiIndex] = None

    def add_index_info(self, index_constitutes: pd.DataFrame, start_date: Union[pd.Timestamp, str] = None,
                       end_date: Union[pd.Timestamp, str] = None, date_format: str = '') -> None:
        """
        adds constitute data to the ConstituteAdjustment object.
        creates and stores a pandas multiIndex index with (date, self.__id_col)
        every date a self.__id_col exists in the equity index it will be in the multiIndex
        method has no side effects on passed data. creates a deep copy of indexConstitutes
        If there are duplicate self.__id_col then a Value error will be raised

        Creates a prices and factors index.
        factors index is simply the range of "from" to "thru"
        Prices indexes have period of the "from" field (df) to end_date param (avoids bias)

        :param index_constitutes: a pandas data frame containing index component information.
                                MUST HAVE COLUMNS: self.__id_col representing the asset identifier,
                                                   'from' start trading date on the index,
                                                   'thru' end trading date on the index,
                                If 'from', 'thru' are not pd.TimeStamps than a date_format MUST BE PASSED.
                                if no date_format is passed its assumed that they are in a pd.TimeStamp object

        :param start_date: The first date we want to get data for, needs to have tz of UTC
        :param end_date: The last first date we want to get data for, needs to have tz of UTC
        :param date_format: if fromCol AND thruCol are both strings then the format to parse them in to dates
        :return: None
        """
        # making sure date and self.__id_col are in the columns
        index_constitutes = _check_columns([self.__id_col, 'from', 'thru'], index_constitutes)

        # will throw an error if there are duplicate self.__id_col
        _handle_duplicates(df=index_constitutes, out_type='ValueError', name='The column symbols',
                           drop=False, subset=[self.__id_col])

        # seeing if we have to convert from and thru to series of timestamps
        if date_format != '':
            index_constitutes['from'] = pd.to_datetime(index_constitutes['from'], format=date_format) \
                .dt.tz_localize('UTC')
            index_constitutes['thru'] = pd.to_datetime(index_constitutes['thru'], format=date_format) \
                .dt.tz_localize('UTC')

        relevant_cal = mcal.get_calendar('NYSE').valid_days(start_date=start_date, end_date=end_date).to_series()

        # making a list of series to eventually concat
        indexes_factor: List[pd.Series] = []
        indexes_pricing: List[pd.Series] = []

        for row in index_constitutes.iterrows():
            symbol = row[1][self.__id_col]

            # getting the relevant dates for the factor
            date_range_factors: pd.Series = relevant_cal.loc[row[1]['from']: row[1]['thru']]
            # pricing data is only concerned with entrance bc of return calculation
            date_range_prices: pd.Series = relevant_cal.loc[row[1]['from']:]

            # converting to frame and then stacking gives us a df with the index we are making, also speed improvement
            indexes_factor.append(
                date_range_factors.to_frame(symbol).stack()
            )
            indexes_pricing.append(
                date_range_prices.to_frame(symbol).stack()
            )

        # getting the index of the concatenated Series
        self.__index_constitutes_factor = pd.concat(indexes_factor).index.set_names(['date', self.__id_col])
        self.__index_constitutes_pricing = pd.concat(indexes_pricing).index.set_names(['date', self.__id_col])

    def adjust_data_for_membership(self, data: pd.DataFrame, contents: str = 'factor',
                                   date_format: str = '') -> pd.DataFrame:
        """
        adjusts the data set accounting for when assets are a member of the index defined in add_index_info.
        add_index_info must be declared before this method
        this method has no side effects on passed data
        Must contain columns named self.__id_col, 'date' otherwise can have as may columns as desired

        factor:
            Ex: AAPl joined S&P500 on 2012-01-01 and leaves 2015-01-01. GOOGL joined S&P500 on 2014-01-01 and is still
            in the index at the time of end_date passed in add_index_info. When passing data to the
            adjust_data_for_membership method it will only return AAPL factor data in range
            2012-01-01 to 2015-01-01 and google data in the range of 2014-01-01 to the end_date.
        pricing:
            keeping with the example above we would get AAPL pricing data in range 2012-01-01 to end_date and google
            data in the range of 2014-01-01 to the end_date.

        :param data: a pandas dataframe to be filtered.
                    Must have a default index.
                    Must have columns named self.__id_col, 'date'
        :param contents: Is the data set, "pricing" or "factor".
        :param date_format: the format of the date column if the date column is a string.
        :return: a indexed data frame adjusted for index constitutes
        """
        # if the add_index_info is not defined then throw error
        if self.__index_constitutes_factor is None:
            raise ValueError('Index constitutes are not set')

        # making sure date and self.__id_col are in the columns
        data = _check_columns(['date', self.__id_col], data, False)

        # ensuring there is not a period in the date column
        if isinstance(data['date'].dtype, pd.core.dtypes.dtypes.PeriodDtype):
            data['date'] = data['date'].dt.to_timestamp()
            date_format = ''

        # dropping duplicates and throwing a warning if there are any
        data = _handle_duplicates(df=data, out_type='Warning', name='Data', drop=True, subset=['date', self.__id_col])

        # seeing if we have to convert from and thru to series of timestamps
        if date_format != '':
            data['date'] = pd.to_datetime(data['date'], format=date_format)

        if contents == 'pricing':
            reindex_frame = self._fast_reindex(self.__index_constitutes_pricing, data)
        elif contents == 'factor':
            reindex_frame = self._fast_reindex(self.__index_constitutes_factor, data)
        else:
            raise ValueError(
                f'Representation {contents} is not recognised. Valid arguments are "pricing", "factor"')

        # if we have dataframe with 1 column then return series
        if reindex_frame.shape[1] == 1:
            return reindex_frame.iloc[:, 0]

        return reindex_frame

    def _fast_reindex(self, reindex_by: pd.MultiIndex, frame_to_reindex: pd.DataFrame):
        """
        Quickly reindex a pandas dataframe using a join in duckdb
        pandas reindex struggles with efficiently reindexing timestamps this is meant to be a work around to that issue
        :param reindex_by: desired pandas multi index
        :param frame_to_reindex: frame we are reindexing data from
        :return: reindexed dataframe
        """
        reindex_by = reindex_by.to_frame()
        id_cols = f'reindex_by.date, reindex_by.{self.__id_col}'
        factor_cols = ', '.join([col for col in frame_to_reindex.columns if col not in ['date', self.__id_col]])

        query = duckdb.query(f"""
                    SELECT {id_cols}, {factor_cols}
                        FROM reindex_by 
                            left join frame_to_reindex on (reindex_by.date = frame_to_reindex.date) 
                                                    and (reindex_by.{self.__id_col} = frame_to_reindex.{self.__id_col});
                    """)

        return self._set_tz(query.to_df()).set_index(['date', self.__id_col])

    def _set_tz(self, df: pd.DataFrame):
        """
        adjusts the date column according to the self.__date_type
        :param df: the Dataframe which we are adjusting the 'date column' for
        :return: df with date columns adjusted
        """
        if self.__date_type == 'timestamp':
            df['date'] = df['date'].dt.tz_localize('UTC')
        elif self.__date_type == 'period':
            df['date'] = df['date'].dt.to_period('D')
        else:
            raise ValueError(f'{self.__date_type} is not recognised')

        return df

    @property
    def factor_components(self) -> Optional[pd.MultiIndex]:
        """
        :return: Mutable list of tuples which represent the factor index constitutes
        """
        return self.__index_constitutes_factor

    @property
    def pricing_components(self) -> Optional[pd.MultiIndex]:
        """
        :return: Mutable list of tuples which represent the pricing index constitutes
        """
        return self.__index_constitutes_pricing


def _check_columns(needed: List[str], df: pd.DataFrame, index_columns: bool = True) -> pd.DataFrame:
    """
    helper to check if the required columns are present
    raises value error if a col in needed is not in givenCols
    :param needed: list of needed columns
    :param df: df of the factor data for the given data
    :param index_columns: should we index the columns specified in needed when returning the df
    :return: Given dataframe with the correct columns and range index
    """
    if not isinstance(df.index, pd.core.indexes.range.RangeIndex):
        df = df.reset_index()

    for col in needed:
        if col not in df.columns:
            raise ValueError(f'Required column \"{col}\" is not present')

    if index_columns:
        return df[needed]

    return df


#
# utility
#


def _handle_duplicates(df: pd.DataFrame, out_type: str, name: str, drop: bool = False,
                       subset: List[any] = None) -> pd.DataFrame:
    """
    Checking to see if there are duplicates in the given data frame
    if there are duplicates outType will be used
        Ex: give a Warning or raise ValueError
    :param df: The data we are checking
    :param name: the name of the data to give as output
    :param out_type: what to do do if there are duplicates. Currently supports "Warning", "ValueError"
    :param drop: boolean to drop the duplicates or not
        if False no data frame will be returned and vice verse
        this param will not matter if outType is a ValueError
    :param subset: subset of df columns we should check duplicates for
    :return: the given df with duplicates dropped according to drop
    """
    # seeing if there are duplicates in the factor
    dups = df.duplicated(subset=subset)

    if dups.any():
        amount_of_dups = dups.sum()
        out_string = f'{name} is {round(amount_of_dups / len(df), 3)} duplicates, {amount_of_dups} rows\n'
        if out_type == 'Warning':
            Warning(out_string)
        elif out_type == 'ValueError':
            raise ValueError(out_string)
        else:
            raise ValueError(f'out_type {out_type} not recognised')

        # dropping the duplicates
        if drop:
            return df.drop_duplicates(subset=subset, keep='first')

    if drop:
        return df
